/*
 * SimSift Bridge Firmware
 *
 * Transparent AT proxy between USB serial (UART0) and cellular modem (UART1).
 * Both sides use the UART hardware driver - no VFS/stdio blocking.
 * ESP-IDF logging is redirected to silence so UART0 is clean for the bridge.
 *
 * Special commands (intercepted, not forwarded to modem):
 *   +++POWERKEY\n  → pulse PWRKEY GPIO
 *   +++RESET\n     → hard reset via RST GPIO
 *   +++BOARD\n     → reply "+BOARD:<name>\r\n"
 *   +++BAUD:<n>\n  → change modem UART baud rate
 */

#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_log.h"

#define USB_UART    UART_NUM_0
#define MODEM_UART  UART_NUM_1
#define USB_BAUD    115200
#define BUF_SIZE    1024

static const char *TAG = "simsift";

/* ── Silent log redirect - keeps UART0 clean ──────────────────────────────── */

static int _noop_vprintf(const char *fmt, va_list args) { return 0; }

/* ── GPIO helpers ────────────────────────────────────────────────────────── */

static void gpio_out(int pin, int level)
{
    if (pin < 0) return;
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    gpio_set_level(pin, level);
}

static void modem_power_on(void)
{
#if CONFIG_SIMSIFT_MODEM_PWR_EN >= 0
    gpio_out(CONFIG_SIMSIFT_MODEM_PWR_EN, 1);
    vTaskDelay(pdMS_TO_TICKS(100));
#endif
    gpio_out(CONFIG_SIMSIFT_MODEM_PWRKEY, 1);
    vTaskDelay(pdMS_TO_TICKS(100));
    gpio_out(CONFIG_SIMSIFT_MODEM_PWRKEY, 0);
    vTaskDelay(pdMS_TO_TICKS(1200));
    gpio_out(CONFIG_SIMSIFT_MODEM_PWRKEY, 1);
    vTaskDelay(pdMS_TO_TICKS(3000));
}

static void modem_reset(void)
{
#if CONFIG_SIMSIFT_MODEM_RST >= 0
    gpio_out(CONFIG_SIMSIFT_MODEM_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(200));
    gpio_out(CONFIG_SIMSIFT_MODEM_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(3000));
#else
    modem_power_on();
#endif
}

/* ── Write to USB ────────────────────────────────────────────────────────── */

static void usb_write(const char *data, int len)
{
    uart_write_bytes(USB_UART, data, len);
}

static void usb_puts(const char *s)
{
    usb_write(s, strlen(s));
}

/* ── Special command handler ─────────────────────────────────────────────── */

static void handle_special(const char *cmd)
{
    if (strcmp(cmd, "+++POWERKEY") == 0) {
        usb_puts("+OK:POWERKEY\r\n");
        modem_power_on();
    } else if (strcmp(cmd, "+++RESET") == 0) {
        usb_puts("+OK:RESET\r\n");
        modem_reset();
    } else if (strcmp(cmd, "+++BOARD") == 0) {
        char resp[64];
        int n = snprintf(resp, sizeof(resp),
                         "+BOARD:%s\r\n", CONFIG_SIMSIFT_BOARD_NAME);
        usb_write(resp, n);
    } else if (strncmp(cmd, "+++BAUD:", 8) == 0) {
        int baud = atoi(cmd + 8);
        if (baud > 0) {
            uart_set_baudrate(MODEM_UART, (uint32_t)baud);
            usb_puts("+OK:BAUD\r\n");
        } else {
            usb_puts("+ERR:BAUD\r\n");
        }
    } else {
        usb_puts("+ERR:UNKNOWN\r\n");
    }
}

/* ── USB → Modem task ────────────────────────────────────────────────────── */

static void usb_to_modem(void *arg)
{
    uint8_t  raw[BUF_SIZE];
    char     line[BUF_SIZE];
    int      line_len = 0;

    while (1) {
        int n = uart_read_bytes(USB_UART, raw, sizeof(raw) - 1,
                                pdMS_TO_TICKS(20));
        if (n <= 0) continue;

        for (int i = 0; i < n; i++) {
            char c = (char)raw[i];

            if (c == '\n') {
                /* Strip trailing \r */
                if (line_len > 0 && line[line_len - 1] == '\r')
                    line_len--;
                line[line_len] = '\0';

                if (line_len >= 3 &&
                    line[0] == '+' && line[1] == '+' && line[2] == '+') {
                    handle_special(line);
                } else if (line_len > 0) {
                    uart_write_bytes(MODEM_UART, line, line_len);
                    uart_write_bytes(MODEM_UART, "\r\n", 2);
                }
                line_len = 0;
            } else {
                if (line_len < BUF_SIZE - 1)
                    line[line_len++] = c;
            }
        }
    }
}

/* ── Modem → USB task ────────────────────────────────────────────────────── */

static void modem_to_usb(void *arg)
{
    uint8_t *buf = malloc(BUF_SIZE);

    while (1) {
        int n = uart_read_bytes(MODEM_UART, buf, BUF_SIZE - 1,
                                pdMS_TO_TICKS(20));
        if (n > 0)
            uart_write_bytes(USB_UART, (char *)buf, n);
    }
}

/* ── app_main ─────────────────────────────────────────────────────────────── */

void app_main(void)
{
    /* Silence logs - UART0 belongs to the bridge */
    esp_log_set_vprintf(_noop_vprintf);

    /* USB UART (UART0) - install driver, keep default pins (TX=1, RX=3) */
    uart_config_t usb_cfg = {
        .baud_rate  = USB_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
    };
    uart_param_config(USB_UART, &usb_cfg);
    uart_driver_install(USB_UART, BUF_SIZE * 2, BUF_SIZE * 2, 0, NULL, 0);

    /* Modem UART (UART1) */
    uart_config_t modem_cfg = {
        .baud_rate  = CONFIG_SIMSIFT_MODEM_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
    };
    uart_param_config(MODEM_UART, &modem_cfg);
    uart_set_pin(MODEM_UART,
                 CONFIG_SIMSIFT_MODEM_TX, CONFIG_SIMSIFT_MODEM_RX,
                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    uart_driver_install(MODEM_UART, BUF_SIZE * 2, BUF_SIZE * 2, 0, NULL, 0);

    /* Signal ready - Python handles modem power via +++POWERKEY if needed */
    usb_puts("+SIMSIFT:READY\r\n");

    xTaskCreate(usb_to_modem, "usb2modem", 4096, NULL, 5, NULL);
    xTaskCreate(modem_to_usb, "modem2usb", 4096, NULL, 5, NULL);
}
