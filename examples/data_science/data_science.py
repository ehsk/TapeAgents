import datetime
import logging
import sys

from tapeagents.agent import Agent
from tapeagents.autogen_prompts import DEFAULT_TEAM_AGENT_SYSTEM_MESSAGE
from tapeagents.container_executor import ContainerExecutor
from tapeagents.core import Action, FinalStep, Observation, Tape
from tapeagents.environment import CodeExecutionEnvironment, Environment
from tapeagents.llms import LLM, LiteLLM
from tapeagents.renderers.camera_ready_renderer import CameraReadyRenderer
from tapeagents.rendering import BasicRenderer, PrettyRenderer
from tapeagents.orchestrator import main_loop
from tapeagents.team import TeamAgent, TeamTape
from tapeagents.view import Call, Respond

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def make_world(llm: LLM | None = None, env: Environment | None = None) -> tuple[Agent, Tape, Environment]:
    llm = llm or LiteLLM(model_name="gpt-4o", parameters={"timeout": 15.0})
    coder = TeamAgent.create(
        name="SoftwareEngineer",
        system_prompt=(
            DEFAULT_TEAM_AGENT_SYSTEM_MESSAGE
            + " Always start by installing packages your code need in a `install.sh` file. ."
            + " Always print in the code the filename of the generated files."
        ),
        llm=llm,
    )
    code_executor = TeamAgent.create(
        name="CodeExecutor",
        llm=llm,
        execute_code=True,
    )
    analyst = TeamAgent.create(
        name="AssetReviewer",
        system_prompt=(
            """As an asset reviewer, your role is to provide one-time feedback to enhance the generated assets. Only communicate your feedback, not a solution.
            Here is a list of best practices:
            - Compare stocks based on percentage changes, using a baseline at 0%.
            - Show the baseline in the plot.
            - Annotate the latest data points in the plot.
            Once your feedback has been implemented and the code runs successfully, simply respond with "TERMINATE".
            """
        ),
        llm=llm,
    )
    team = TeamAgent.create_team_manager(
        name="Manager",
        subagents=[coder, code_executor, analyst],
        max_calls=15,
        llm=llm,
    )
    org = TeamAgent.create_initiator(
        name="Initiator",
        init_message=(
            "Make a plot comparing the stocks of ServiceNow and Salesforce"
            " since beginning of 2024."
        ),
        teammate=team,
    )
    start_tape = TeamTape(context=None, steps=[])
    now = f"{datetime.datetime.now():%Y%m%d%H%M%S}"
    env = env or CodeExecutionEnvironment(ContainerExecutor(work_dir=f"outputs/data_science/{now}"))
    return org, start_tape, env


def make_renderers() -> dict[str, BasicRenderer]:
    return {
        "camera-ready": CameraReadyRenderer(),
        "camera-ready_nocontent": CameraReadyRenderer(show_content=False),
        "camera-ready_nocontent-nollmcalls": CameraReadyRenderer(show_content=False, render_llm_calls=False),
        "full": PrettyRenderer(),
        "calls_and_responses": PrettyRenderer(filter_steps=(Call, Respond, FinalStep), render_llm_calls=False),
        "actions_and_observations": PrettyRenderer(filter_steps=(Action, Observation), render_llm_calls=False),
    }


def main(studio: bool):
    agent, start_tape, env = make_world()
    if studio:
        from tapeagents.studio import Studio

        Studio(agent, start_tape, make_renderers(), env).launch()
    else:
        final_tape = main_loop(agent, start_tape, env).get_final_tape()
        with open("final_tape.json", "w") as f:
            f.write(final_tape.model_dump_json(indent=2))


if __name__ == "__main__":
    match sys.argv[1:]:
        case []:
            main(studio=False)
        case ["studio"]:
            main(studio=True)
        case _:
            print("Usage: python -m examples.data_science.data_science [studio]")
            sys.exit(1)
