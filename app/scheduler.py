import logging
import time

from app.settings import Settings

logger = logging.getLogger(__name__)


def run_worker(settings: Settings) -> None:
    if settings.run_mode == "once":
        from app.main import run_once

        run_once(settings)
        return

    if settings.run_mode == "worker":
        from app.main import run_once

        logger.info(
            "PromoFlash Bot iniciado em modo worker (intervalo: %ss)",
            settings.sleep_interval_seconds,
        )
        while True:
            run_once(settings)
            logger.info("Aguardando %s segundos...", settings.sleep_interval_seconds)
            time.sleep(settings.sleep_interval_seconds)
        return

    raise ValueError(f"RUN_MODE inválido: {settings.run_mode}")
