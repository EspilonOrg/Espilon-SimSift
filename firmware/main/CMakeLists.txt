idf_component_register(
    SRCS "bridge.c"
    INCLUDE_DIRS "."
    REQUIRES driver freertos esp_system log
)
