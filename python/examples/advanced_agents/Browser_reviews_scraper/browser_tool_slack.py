from langchain.agents import create_openai_functions_agent, AgentExecutor
from langchain import hub
from langchain_openai import ChatOpenAI
from composio_langchain import ComposioToolSet
from composio import Action
from openai import OpenAI

llm = ChatOpenAI()
from composio.client.collections import TriggerEventData
import asyncio
import logging

prompt = hub.pull("hwchase17/openai-functions-agent")

composio_toolset = ComposioToolSet(api_key="fcau1ynif45lumo8txt5o", connected_account_ids={})
tools = composio_toolset.get_tools(actions=['BROWSER_TOOL_GET_PAGE_DETAILS','BROWSER_TOOL_GOTO_PAGE', 'BROWSER_TOOL_SCROLL_PAGE', 'BROWSER_TOOL_REFRESH_PAGE', 'SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL'])
openai_client = OpenAI()

agent = create_openai_functions_agent(llm, tools, prompt)
agent_executor = AgentExecutor(
    agent=agent, 
    tools=tools, 
    verbose=True,
    handle_parsing_errors=True
)

listener = composio_toolset.create_trigger_listener()
@listener.callback(filters={"trigger_name": "slack_receive_message"})
def handle_slack_message(event: TriggerEventData):
    payload = event.payload
    message = payload.get("text", "")
    channel_id = payload.get("channel", "")
    if channel_id != "<add channel id here>":
        return
    print(message)
    print(channel_id)
    composio_toolset.execute_action(
        action=Action.SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL,
        params={
            "channel": "<add channel id here>",
            "text": f"Collating responses using the composio browser tool......."
        },
    )
    print("Message sent to Slack channel. Waiting for user response...")
    get_reviews(message)


def get_reviews(url):
    tasks = [
        f"Go to {url}",
        "Wait for the page to fully load and verify the content is accessible",
        "scroll down the page",
        "Locate the customer reviews",
        "Keep repeating the process till you find all the reviews",
        "Analyze all customer reviews on the page and provide a concise summary that includes: \
         \n- Overall rating and total number of reviews \
         \n- Key positive points mentioned frequently \
         \n- Common complaints or issues \
         \n- Notable specific feedback about product features \
         \nKeep the summary focused on helping potential buyers make an informed decision."
        "Format the summary and send the summary to the slack channel with id <add channel id here>"
    ]

    for task in tasks:
        try:
            result = agent_executor.invoke({"input": task})
            print(f"Task: {task}")
            print(f"Result: {result}\n")
        except Exception as e:
            print(f"Error executing task '{task}': {str(e)}\n")


async def main():
    logging.info("AI Agent started. Listening for Slack messages and Gmail emails...")
    # Run the agent and listener concurrently
    await asyncio.gather(asyncio.to_thread(listener.listen))
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Program terminated by user.")