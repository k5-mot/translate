"""公開CLI起動前に外部service境界のE2E driverを導入する。"""

from tests.e2e import cli_driver  # noqa: F401 - import時にCLI境界を置換する。
