SCENARIOS = [
    {"name": "slow_drift", "text": "通道线性慢漂移"},
    {"name": "sudden_bias", "text": "通道固定偏置"},
    {"name": "vacuum_leak", "text": "真空泄漏"},
    {"name": "packet_loss", "text": "通信丢包"},
]

FAULT_CATALOG = [
    {"kind": kind, "layer": layer, "alarms": alarms == "1"}
    for kind, layer, alarms in (
        ("SENSOR_99999", "sensor", "1"),
        ("EARLY_STOP", "sensor", "1"),
        ("PACKET_LOSS", "communication", "1"),
        ("heater_dead", "actuator", "0"),
        ("VACUUM_LEAK", "actuator", "1"),
        ("CYLINDER_STUCK", "actuator", "1"),
        ("AMBIENT_EXCURSION", "environment", "1"),
        ("COMM_DISCONNECT", "communication", "1"),
        ("COMM_DELAY", "communication", "1"),
        ("PLC_FAULT", "plc", "1"),
        ("THERMAL_BOARD_DISCONNECT", "sensor", "1"),
        ("HEATER_POWER_LOSS", "actuator", "1"),
        ("DUPLICATE_REPORT", "communication", "1"),
        ("FIELD_MISALIGNMENT", "communication", "1"),
        ("SENSOR_SPIKE", "sensor", "1"),
        ("ROBOT_PICK_FAIL", "actuator", "1"),
        ("power_bias", "actuator", "0"),
        ("force_axis_drift", "actuator", "0"),
        ("contact_degraded", "actuator", "0"),
        ("SENSOR_OPEN", "sensor", "1"),
        ("SENSOR_9999", "sensor", "1"),
        ("SENSOR_UNPARSEABLE", "sensor", "1"),
        ("SENSOR_STUCK", "sensor", "1"),
        ("PRESS_TIMEOUT", "actuator", "1"),
        ("HEATER_RUNAWAY", "actuator", "1"),
        ("poor_contact", "fixture", "0"),
    )
]
