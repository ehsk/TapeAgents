import json
import logging
import os
import sys

import yaml

from tapeagents.io import save_json_tape

from ..eval import load_dataset, load_results
from ..tape import GaiaTape

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


def main(exp_path: str) -> None:
    config_path = os.path.join(exp_path, ".hydra", "config.yaml")
    assert os.path.exists(config_path), f"Config file {config_path} not found"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    data_dir = cfg["data_dir"]
    model_name = cfg["llm"]["model_name"]
    tasks = load_dataset(data_dir)
    tapes_dir = os.path.join(exp_path, "tapes")
    os.makedirs(tapes_dir, exist_ok=True)
    for level, level_tasks in tasks.items():
        outfile = os.path.join(exp_path, f"l{level}_{model_name}_run.json")
        logger.info(f"Convert level {level} with {len(level_tasks)} from {outfile}")
        assert os.path.exists(outfile)
        results = load_results(outfile)
        logger.info(f"Loaded solutions for {len(results.tapes)} tasks")
        for i in range(len(level_tasks)):
            old_tape = results.tapes[i] if i < len(results.tapes) else None
            if old_tape is None:
                logger.info(f"Skipping task {i} as tape not found")
                continue
            save_json_tape(GaiaTape.model_validate(old_tape), tapes_dir, f"l{level}_task{i}")
        logger.info(f"Converted {len(level_tasks)} tasks to tapes")
        with open(os.path.join(exp_path, "browser_log.jsonl"), "a") as wf:
            for k, v in results.web_cache.items():
                wf.write(json.dumps({"k": k, "v": v}) + "\n")
    logger.info("Done")


if __name__ == "__main__":
    assert len(sys.argv) == 2, "Usage: examples.gaia_agent.scripts.convert_legacy <exp_dir>"
    main(sys.argv[1])
