import logging
from typing import Callable, Generator, Mapping

import gradio as gr
import yaml

from tapeagents.environment import Environment
from tapeagents.observe import get_latest_tape_id, observe_tape, retrieve_tape_llm_calls, retrieve_tape
from tapeagents.runtime import main_loop

from .agent import Agent
from .core import Tape
from .rendering import BasicRenderer, render_agent_tree

logger = logging.getLogger(__name__)


class Studio:

    def __init__(
        self, 
        agent: Agent,
        tape: Tape, 
        renderers: BasicRenderer | Mapping[str, BasicRenderer],
        environment: Environment | None = None,
        transforms: Mapping[str, Callable[[Tape], Tape]] | None = None
    ):
        self.renderers = {"renderer": renderers} if isinstance(renderers, BasicRenderer) else renderers
        self.environment = environment
        self.transforms = transforms or {}

        with gr.Blocks(title="TapeAgent Studio") as blocks:
            tape_state = gr.State(tape)
            agent_state = gr.State(agent)
            with gr.Row():
                with gr.Column():
                    tape_data = gr.Textbox(
                        "", max_lines=15, label="Raw Tape content", info="Press Enter to rerender the tape"
                    )
                    pop = gr.Number(1, label="Pop N last steps", info="Press Enter to proceed")
                    keep = gr.Number(0, label="Keep N first steps", info="Press Enter to proceed")
                    load = gr.Textbox(max_lines=1, label="Load tape by id", info="Press Enter to load tape")
                    choices = list(self.renderers.keys())
                    renderer_choice = gr.Dropdown(choices=choices, value=choices[0], label="Choose the tape renderer")
                    if transforms:
                       transform_choice = gr.Dropdown(list(transforms.keys()), label="Run a transform")
                with gr.Column():
                    tape_render = gr.HTML("")
                with gr.Column():
                    org_chart = gr.TextArea(render_agent_tree(agent), max_lines=6, label="Agent Org Chart")
                    agent_config = gr.Textbox(
                        "",
                        max_lines=15,
                        label="Agent configuration",
                        info="Press Enter to update the agent",
                    )
                    run_agent = gr.Button("Run Agent")
                    if environment:
                        run_enviroment = gr.Button("Run Environment")
                        run_loop = gr.Button("Run Loop")
                    else: 
                        run_enviroment = None
                        run_loop = None

            render_tape = (
                self.render_tape, [renderer_choice, tape_state], [tape_data, tape_render]
            )

            blocks.load(
                *render_tape
            ).then(
                self.render_agent, [agent_state], [agent_config]
            )

            # Tape controls
            tape_data.submit(
                lambda data: tape.model_validate(yaml.safe_load(data)).with_new_id(), 
                [tape_data], [tape_state]
            ).then(
                *render_tape
            ).then(
                lambda tape: observe_tape(tape), [tape_state], []
            )            
            pop.submit(
                self.pop_n_steps, [tape_state, pop], [tape_state]
            ).then(
                *render_tape
            )
            keep.submit(
                self.keep_n_steps, [tape_state, keep], [tape_state]
            ).then(
                *render_tape
            )
            load.submit(
                self.load_tape, [tape_state, load], [tape_state]
            ).then(
                *render_tape
            )
            renderer_choice.change(
                *render_tape
            )
            if transforms:
                transform_choice.change(
                    lambda transform, tape: self.transforms[transform](tape), 
                    [transform_choice, tape_state], [tape_state]
                ).then(
                    *render_tape
                )            

            # Agent controls
            agent_config.submit(
                self.update_agent, 
                [agent_config, agent_state], [agent_state]
            ).then(
                lambda: gr.Info("Agent updated")
            )
            run_agent.click(
                self.run_agent, 
                [renderer_choice, agent_state, tape_state], [tape_state, tape_data, tape_render]
            )
            if environment:
                assert run_enviroment and run_loop
                run_enviroment.click(
                    self.run_environment, [tape_state], [tape_state]
                ).then(
                    *render_tape
                )
                run_loop.click(
                    self.run_main_loop, 
                    [renderer_choice, agent_state, tape_state], [tape_state, tape_data, tape_render]
                )

        self.blocks = blocks

    def pop_n_steps(self, tape: Tape, n: int) -> Tape:
        if n > len(tape):
            raise gr.Error(f"Cannot pop {n} steps from tape with {len(tape)} steps")
        return tape[:-n]

    def keep_n_steps(self, tape: Tape, n: int) -> Tape:
        if n > len(tape):
            raise gr.Error(f"Cannot keep {n} steps from tape with {len(tape)} steps")
        return tape[:n]
    
    def transform_tape(self, transform: str, tape: Tape) -> Tape:
        result = self.transforms[transform](tape)
        observe_tape(result)
        return result
    
    def load_tape(self, cur_tape: Tape, tape_id: str) -> Tape:
        if not tape_id:
            tape_id = get_latest_tape_id()
        result = retrieve_tape(type(cur_tape), tape_id)
        if not result:
            raise gr.Error(f"No tape found with id {tape_id}")
        return result

    def render_tape(self, renderer_name: str, tape: Tape) -> tuple[str, str]:
        renderer = self.renderers[renderer_name]
        llm_calls = retrieve_tape_llm_calls(tape)
        return (yaml.dump(tape.model_dump(), sort_keys=False), renderer.style + renderer.render_tape(tape, llm_calls))

    def render_agent(self, agent: Agent) -> str:
        return yaml.dump(agent.model_dump(), sort_keys=False)

    def update_agent(self, config: str, agent: Agent) -> Agent:
        return agent.update(yaml.safe_load(config))

    def run_agent(self, renderer_name: str, agent: Agent, start_tape: Tape) -> Generator[tuple[Tape, str, str], None, None]:
        for event in agent.run(start_tape):
            if tape := event.partial_tape or event.final_tape:
                observe_tape(tape)
                yield (tape,) + self.render_tape(renderer_name, tape)

    def run_environment(self, tape: Tape) -> Tape:
        assert self.environment
        return self.environment.react(tape)
    
    def run_main_loop(self, renderer_name: str, agent: Agent, start_tape: Tape) -> Generator[tuple[Tape, str, str], None, None]:
        assert self.environment
        last_tape = start_tape
        for event in main_loop(agent, start_tape, self.environment):
            if ae := event.agent_event:
                if tape := ae.partial_tape or ae.final_tape:
                    observe_tape(tape)
                    logger.info(f"added step {type(ae.step).__name__}")
                    last_tape = tape
                    yield (tape,) + self.render_tape(renderer_name, tape)
            elif event.observation:
                last_tape = last_tape.append(event.observation)
                yield (last_tape,) + self.render_tape(renderer_name, last_tape)
            else:
                raise ValueError("Unexpected event")

    def launch(self, *args, **kwargs):
        self.blocks.launch(*args, **kwargs)