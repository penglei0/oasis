import logging
import os


def configure_run_logging(debug_enabled: bool, root_path: str):
    log_level = logging.DEBUG if debug_enabled else logging.INFO
    log_dir = os.path.join(root_path, "test_results")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "oasis.log")
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
        ],
        force=True,
    )
