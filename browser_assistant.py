import asyncio
from browser_use import Agent
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv

async def run_browser_task(task: str):
    """
    Run a browser task using Browser Use agent
    """
    try:
        # Initialize the LLM using OpenRouter API key
        llm = ChatOpenAI(
            model="openai/gpt-4",  # Using OpenAI's model through OpenRouter
            api_key=os.getenv('OPENROUTER_API_KEY'),
            base_url="https://openrouter.ai/api/v1",
            temperature=0
        )
        
        # Create the agent
        agent = Agent(
            task=task,
            llm=llm,
            use_vision=True,  # Enable vision capabilities for better web interaction
            save_conversation_path="logs/conversation.json"  # Save logs for debugging
        )

        # Run the agent and get history
        history = await agent.run()

        # Print results
        print("\n=== Task Completed ===")
        print("Visited URLs:", history.urls())
        print("Final Result:", history.final_result())
        
        if history.has_errors():
            print("\nErrors encountered:", history.errors())

    except Exception as e:
        print(f"An error occurred: {str(e)}")

async def main():
    """
    Main function to run the browser assistant
    """
    # Load environment variables
    load_dotenv()
    
    # Ensure OPENROUTER_API_KEY is set
    if not os.getenv("OPENROUTER_API_KEY"):
        print("Please set your OPENROUTER_API_KEY in the .env file")
        return

    print("=== Browser Assistant ===")
    print("Type 'exit' to end the session")
    
    while True:
        # Get user input
        task = input("\nWhat would you like me to do in the browser? \n> ")
        
        if task.lower() == 'exit':
            break
            
        if task.strip():
            print("\nExecuting task...")
            await run_browser_task(task)

if __name__ == "__main__":
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Run the main function
    asyncio.run(main()) 