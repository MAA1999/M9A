from importlib import import_module

ACTION_MODULES = (
    "general",
    "activity",
    "bank",
    "combat",
    "lucidscape",
    "wilderness",
    "outside_deduction",
    "reveries_in_the_rain",
    "syndrome_of_silence",
    "critter_crash",
    "redeem_code",
    "reward",
    "record_id",
    "switch_account",
    "complete_induction",
    "eight_bit",
)


def register_all() -> None:
    for module_name in ACTION_MODULES:
        import_module(f"custom.action.{module_name}")


__all__ = ["register_all"]
