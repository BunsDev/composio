import argparse
import os
import random
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from langchain_aws import BedrockChat
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError

from composio_langgraph import Action

from swekit.benchmark.run_evaluation import evaluate
from swekit.config.store import IssueConfig

from agent import get_agent_graph


max_retries = 5
base_delay = 1  # in seconds


MODEL = "openai"


def retry_with_exponential_backoff(func, *args, **kwargs):
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            delay = (2**attempt) * base_delay
            time.sleep(delay)


def get_llm_response(system_prompt: str, human_prompt: str) -> str:
    try:
        if MODEL == "claude":
            client = BedrockChat(
                credentials_profile_name="default",
                model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
                region_name="us-west-2",
                model_kwargs={"temperature": 0},
            )
            response = retry_with_exponential_backoff(
                client.invoke, [("system", system_prompt), ("human", human_prompt)]
            )
        else:
            client = ChatOpenAI(
                model="o1-mini",
                temperature=1,
                max_completion_tokens=4096,
                api_key=openai_api_key,
            )
            response = retry_with_exponential_backoff(
                client.invoke, [("human", human_prompt)]
            )
        return response.content
    except Exception:
        return f"Error while calling llm {MODEL}: \n{traceback.format_exc()}\n"


def build_comparison_prompt(repo_name: str, issue_desc: str, patch_str: str) -> str:
    return """
I am facing the following issue in the repo {repo_name}. You have an older version of the codebase, so your belief about the 
codebase might be outdated. Some agents tried to solve the issue and generated patches. Your task is to choose the best patch that fixes the issue,
or the ask the agents to run again, if you are not confident that the patches fix the issue. To help you, I have also provided a summary of the 
run of the agent. 

Issue Description:
{issue_desc}

You are given multiple patches and details of the agent's run, and you need to check which one fixes the issue. 
Only one of the patch will fix the issue.

{patch_str}

First analyse all the patches thoroughly and then choose the best patch that fixes the issue. You need to 
consider all the edge cases very carefully. The chosen patch might be more verbose, but it should pass all the 
possible test cases regarding the issue. Choose a patch if you are ABSOLUTELY SURE THAT THE PATCH SOLVES THE ISSUE.

If you feel none of the patches fixes the issue, respond with "RUN AGAIN". Also give a detailed one paragraph of reasoning why you feel
none the patches is a correct solution to the problem. Analyse the runs of the agents as well and provide what the agents did wrong. The resoning must focus
on the aspects that the agent should take care of in future runs, as well as a summary of the patches generated by the agents.


NOTE: ONLY JUDGE THE PATCHES BASED ON THE CHANGES IN THE SOURCE CODE.
IGNORE THE CHANGES IN THE TESTS, DOCS OR OTHER FILES.
RESPONE WITH THE PATCH NUMBER AND REASONING ONLY IF YOU ARE ABSOLUTELY CONFIDENT THAT THE PATCH FIXED THE ISSUE. RESPOND WITH "RUN AGAIN" OTHERWISE WITH PROPER REASONING.
YOU DON'T NEED TO WORRY ABOUT THE TESTS. ONLY JUDGE THE PATCHES BASED ON THE CHANGES IN SOURCE CODE.

If you are absolutely confident that one of the patches fixes the issue and decide to submit the patch from Provide your response in the following format:
{{
    "patch": "The number of the patch that best fixes the issue (1, 2, 3, ...)",
    "reasoning": "Your explanation for why the chosen patch fixes the issue",
    "confidence": "How confident are you that the patch fixes the issue? (0-100)"
}}

If you feel that none of the patches fixes the issue, decide to reject the patches and run again, provide your response in the format:
{{
    "patch": "RUN AGAIN",
    "reasoning": "The detailed reason why none of the patch can fix the issue. Summarise the patches as well, so that next software engineer has the whole context about the
patches and reason of their failures." 
}}
Please adhere to the json format strictly.
""".format(
        repo_name=repo_name, issue_desc=issue_desc, patch_str=patch_str
    )


def build_comparison_prompt_hard(
    repo_name: str, issue_desc: str, patch_str: str
) -> str:

    return """
I am facing the following issue in the repo {repo_name}. You have an older version of the codebase, so your belief about the 
codebase might be outdated. Some agents tried to solve the issue and generated patches. Your task is to choose the best patch that fixes the issue.
Issue Description:
{issue_desc}

You are given multiple patches and details of the agent's run, and you need to check which one fixes the issue. 
Only one of the patch will fix the issue.

{patch_str}

First analyse all the patches thoroughly and then choose the best patch that fixes the issue. You need to 
consider all the edge cases very carefully. The chosen patch might be more verbose, but it should pass all the 
possible test cases regarding the issue.

NOTE: ONLY JUDGE THE PATCHES BASED ON THE CHANGES IN THE SOURCE CODE.
IGNORE THE CHANGES IN THE TESTS, DOCS OR OTHER FILES.

Provide your response in the following format:
{{
    "patch": "The number of the patch that best fixes the issue (1, 2, 3, ...)",
    "reasoning": "Your explanation for why the chosen patch fixes the issue",
}}
""".format(
        repo_name=repo_name, issue_desc=issue_desc, patch_str=patch_str
    )


def choose_patch(
    patches, issue_config: IssueConfig, run_contents: List[str], hard=False
):
    if not patches:
        return "", False

    run_summaries = []
    for run_content in run_contents:
        summary_response = get_llm_response(
            system_prompt="You are an expert summarizer of agent's output.",
            human_prompt=f"The following is the run of the agent after it tried to fix the issue. Analyse the contents and messages of the run and give a short summary of what the agent did. \n{run_content}. Provide the output in the form of 5-7 chronological points.",  # noqa: E501
        )
        run_summaries.append(summary_response)

    patch_str = ""
    for i, patch in enumerate(patches):
        run_summary = run_summaries[i]
        patch_str += "=" * 50
        patch_str += f"\nPatch {i+1}:\n{patch}"
        if not hard:
            patch_str += f"\nSummary of the agent:\n{run_summary}\n"
    patch_str += "=" * 50

    if not hard:
        response = get_llm_response(
            system_prompt="You are a software engineer expert at solving bugs.",
            human_prompt=build_comparison_prompt(
                repo_name=issue_config.repo_name.split("/")[-1],
                issue_desc=issue_config.issue_desc,
                patch_str=patch_str,
            ),
        )
    else:
        response = get_llm_response(
            system_prompt="You are a software engineer expert at solving bugs.",
            human_prompt=build_comparison_prompt_hard(
                repo_name=issue_config.repo_name.split("/")[-1],
                issue_desc=issue_config.issue_desc,
                patch_str=patch_str,
            ),
        )
    if "RUN AGAIN" in response:
        return response, False

    print("Response", response)
    if response:
        try:
            match = re.search(r"patch.*?(\d+)", response, re.IGNORECASE)
            if match:
                patch_number = int(match.group(1))
                if 1 <= patch_number <= len(patches):
                    return patches[patch_number - 1], True

            open("error.txt", "w").write(response)
            return random.choice(patches), True
        except Exception as e:
            open("error.txt", "w").write(response)
            print(f"Error in response: {e}")
            return random.choice(patches), True
    else:
        open("error.txt", "w").write(response)
        print("No response content found")
        return random.choice(patches), True


def bench(workspace_ids: str, issue_config: IssueConfig) -> str:
    patch = ""
    patch_list = []
    for _ in range(3):
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(run_agent_function, workspace_id, issue_config, patch)
                for workspace_id in workspace_ids
            ]
            patches = []
            run_contents = []
            for future in as_completed(futures):
                try:
                    patch, run_content = future.result()
                    if patch:
                        patches.append(patch)
                    run_contents.append(run_content)
                except Exception as e:
                    print(f"Error in future: {e}")
            patch_list.extend(patches)

        patch, success = choose_patch(patches, issue_config, run_contents)

        if success:
            return patch

    patch, success = choose_patch(patches, issue_config, run_contents, hard=True)
    return patch


def get_patch_from_response(composio_toolset, repo_name):
    composio_toolset.execute_action(
        action=Action.FILETOOL_CHANGE_WORKING_DIRECTORY,
        params={"path": f"/home/user/{repo_name}"},
    )
    # if "astropy" in repo_name:
    #     composio_toolset.execute_action(
    #         action=Action.SHELLTOOL_EXEC_COMMAND,
    #         params={"cmd": "git config --global user.email \"you@example.com\""},
    #     )
    #     composio_toolset.execute_action(
    #         action=Action.SHELLTOOL_EXEC_COMMAND,
    #         params={"cmd": "git config --global user.name \"Your Name\""},
    #     )
    #     composio_toolset.execute_action(
    #         action=Action.SHELLTOOL_EXEC_COMMAND,
    #         params={"cmd": "git restore --staged :/"},
    #     )
    #     composio_toolset.execute_action(
    #         action=Action.SHELLTOOL_EXEC_COMMAND,
    #         params={"cmd": "chown -R root:root .git"},
    #     )
    #     composio_toolset.execute_action(
    #         action=Action.SHELLTOOL_EXEC_COMMAND,
    #         params={"cmd": "git add astropy_helpers && git commit -m \"add submodule\""},
    #     )

    get_patch_resp = composio_toolset.execute_action(
        action=Action.FILETOOL_GIT_PATCH,
        params={},
    )

    if not get_patch_resp.get("successful", False):
        error_message = get_patch_resp.get("error")
        if error_message:
            print(f"Error in get_patch: {error_message}")
            return ""
        else:
            print("Unknown error occurred in get_patch")
            return ""

    patch_data = get_patch_resp.get("data", {})
    if not patch_data:
        print("No data found in the patch response")
        return ""
    patch = patch_data.get("patch")
    if not patch:
        error = patch_data.get("error")
        if error:
            print(f"Error in patch data: {error}")
            return ""
        else:
            print("No patch found in the response data")
            return ""

    print(f"Final Patch: {patch}")
    return patch


def run_agent_function(
    workspace_id: str, issue_config: IssueConfig, previous_patch_str: str = ""
):
    """Run benchmark on the agent."""

    graph, composio_toolset, run_file = get_agent_graph(
        repo_name=issue_config.repo_name.split("/")[-1], workspace_id=workspace_id
    )

    # get the git tree
    git_tree_response = composio_toolset.execute_action(
        action=Action.FILETOOL_GIT_REPO_TREE,
        params={},
    )

    composio_toolset.execute_action(
        action=Action.SHELLTOOL_EXEC_COMMAND,
        params={"cmd": f"cd ~/{issue_config.repo_name.split('/')[-1]}"},
    )

    if previous_patch_str != "":
        issue_desc = f"{issue_config.issue_desc}\n. I have already tried to solve this problem before, but failed for the following reason: \n {previous_patch_str}.\n The previous patches did not fix the issue. Now try again to fix the issue. {issue_config.issue_desc}. \n Output to git tree command {git_tree_response}. Pay attention to the reason why patch failed to solve the issue and try something different to fix the issue."  # noqa: E501
    else:
        issue_desc = f"{issue_config.issue_desc}.\n Output to git tree command {git_tree_response}"

    try:
        graph.invoke(
            {"messages": [HumanMessage(content=issue_desc)]},
            {"recursion_limit": 50},
        )
    except GraphRecursionError as e:
        print(f"GraphRecursionError: {e}")
    except Exception as e:
        print(f"Error in graph.invoke: {e}")

    patch = get_patch_from_response(
        composio_toolset, issue_config.repo_name.split("/")[-1]
    )
    run_content = open(run_file, "r").read()
    os.remove(run_file)
    composio_toolset.execute_action(
        action=Action.SHELLTOOL_EXEC_COMMAND,
        params={"cmd": f"git reset --hard {issue_config.base_commit_id}"},
    )

    return patch, run_content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run benchmark on the agent.",
    )
    # group = parser.add_mutually_exclusive_group()
    parser.add_argument(
        "--test-split",
        type=str,
        default="1:2",
        help="Test split ratio (e.g. 1:2, 1:300) Maximum 500 tests per project.",
    )
    parser.add_argument(
        "--test-instance-ids",
        type=str,
        default="",
        help="Test instance ids (comma-separated)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="temp",
        help="Run id",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="princeton-nlp/SWE-bench_Verified",
        help="Dataset",
    )
    parser.add_argument(
        "--num-instances",
        type=int,
        default=1,
        help="Number of instances",
    )
    args = parser.parse_args()

    if args.test_instance_ids:
        test_instance_ids_list = [
            id.strip() for id in args.test_instance_ids.split(",")
        ]
        test_range = "0:500"
    else:
        test_instance_ids_list = []
        test_range = args.test_split

    evaluate(
        bench,
        dataset_name=args.dataset,
        dry_run=False,
        test_range=test_range,
        include_hints=False,
        test_instance_ids=test_instance_ids_list,
        run_id=args.run_id,
        num_instances=args.num_instances,
    )
