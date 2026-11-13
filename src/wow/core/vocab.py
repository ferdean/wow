"""Define the closed vocabularies shared across layers."""

from enum import StrEnum


class Screen(StrEnum):
    """Screen the rider is on."""

    HOME = "home"
    PRE_RIDE = "pre_ride"
    RIDE = "ride"
    SUMMARY = "summary"


class Mode(StrEnum):
    """Trainer control mode."""

    ERG = "erg"
    RESISTANCE = "resistance"


class Problem(StrEnum):
    """Reason a request was refused or a warning is raised."""

    BAD_REQUEST = "bad_request"
    INVALID_STATE = "invalid_state"
    RIDE_RUNNING = "ride_running"
    TRAINER_MISSING = "trainer_missing"
    ERG_UNAVAILABLE = "erg_unavailable"
    NOT_ARMED = "not_armed"
    NOT_RIDING = "not_riding"
    TRAINER_NOT_RESPONDING = "trainer_not_responding"
    CONTROL_REFUSED = "control_refused"
    TARGET_LIMITED = "target_limited"


class CommandName(StrEnum):
    """Name of a command the display can send."""

    OPEN_WORKOUT = "open_workout"
    OPEN_FREE_RIDE = "open_free_ride"
    SET_BLOCK_MODE = "set_block_mode"
    START = "start"
    CANCEL_START = "cancel_start"
    PAUSE = "pause"
    RESUME = "resume"
    SKIP = "skip"
    INTENSITY = "intensity"
    SWITCH_MODE = "switch_mode"
    RESISTANCE = "resistance"
    FREE_RIDE_POWER = "free_ride_power"
    FINISH = "finish"
    DISCARD = "discard"
    BACK = "back"
    OPEN_HISTORY = "open_history"
    OPEN_RIDE = "open_ride"
    UPLOAD_RETRY = "upload_retry"
    DELETE_RIDE = "delete_ride"
    OPEN_CALIBRATION = "open_calibration"
    CALIBRATION_START = "calibration_start"
    CALIBRATION_CANCEL = "calibration_cancel"
    OPEN_SETTINGS = "open_settings"
    SETTINGS_SET = "settings_set"
    INTERVALS_ACCOUNT_SET = "intervals_account_set"
    DEVICE_SCAN = "device_scan"
    DEVICE_CHOOSE = "device_choose"
    RECOVERY_CONTINUE = "recovery_continue"
    RECOVERY_FINISH = "recovery_finish"


class UploadState(StrEnum):
    """Upload state of a ride (ICD IF-06)."""

    OFF = "off"
    PENDING = "pending"
    UPLOADING = "uploading"
    DONE = "done"
    RETRYING = "retrying"
    FAILED = "failed"
    AUTH_ERROR = "auth_error"


class WarningKind(StrEnum):
    """Kind of a warning outside the ride."""

    WORKOUTS_OFFLINE = "workouts_offline"
