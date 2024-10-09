import contextlib
import os
from pathlib import Path
import shutil
import tempfile

import tapeagents.observe


@contextlib.contextmanager
def run_test_in_tmp_dir(test_name: str):
    """Copy test resources to a temporary directory and run the test there"""
    cur_dir = os.getcwd()
    tmpdir = tempfile.mkdtemp()
    test_data_dir = Path(f"tests/res/{test_name}").resolve()
    os.chdir(tmpdir)
    shutil.copytree(test_data_dir, tmpdir, dirs_exist_ok=True)
    # force creation of SQLite tables
    tapeagents.observe._checked_sqlite = False
    yield
    os.chdir(cur_dir)


@contextlib.contextmanager
def run_in_tmp_dir_to_make_test_data(test_name: str, keep_llm_cache=False):
    tmpdir = tempfile.mkdtemp()
    os.chdir(tmpdir)
    try:
        yield
    # find all non-directory files that got created
    finally:
        created_files = []
        for root, _, files in os.walk(tmpdir):
            for file in files:
                # For most of the code we test in TapeAgents we create ReplayLLM
                # that looks up prompts and outputs in the SQLite database. For this
                # reason, by default we don't save the LLM cache files. If you want
                # make test data for a Jupyter notebook, you can use the keep_llm_cache
                # to save the LLM cache files.
                if file.startswith("llm_cache") and not keep_llm_cache:
                    continue
                created_files.append(os.path.relpath(os.path.join(root, file), tmpdir))
        cp_source = " ".join(f"$TMP/{f}" for f in created_files)
        test_data_dir = f"tests/res/{test_name}"
        print("Saved test data to ", tmpdir)
        print("To update test data, run these commands:")
        print(f"mkdir {test_data_dir}")
        print(f"TMP={tmpdir}; cp {cp_source} {test_data_dir}")