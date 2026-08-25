#!/usr/bin/env python3
"""
Managed Deep Agent Configuration for EUREKA - Simplified Version
Using google_genai:gemini-3.5-flash-lite with current LangChain API
"""

import os
import json
from typing import Dict, Any, Optional

# Import required libraries
try:
    import google.generativeai as genai
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.tools import tool
    from langchain.agents import create_tool_calling_agent
    from langchain.agents import AgentExecutor
    from langchain_core.messages import AIMessage, HumanMessage
except ImportError as e:
    print(f"Error importing required libraries: {e}")
    print("Please make sure you have installed: google-generativeai, langchain")
    exit(1)

class ManagedDeepAgentSimple:
    """
    Simplified Managed Deep Agent for EUREKA using Google Gemini
    """

    def __init__(self, agent_name: str = "my-agent", api_key: Optional[str] = None):
        """
        Initialize the Managed Deep Agent

        Args:
            agent_name: Name of the agent
            api_key: Google API key (optional, can be set via environment variable)
        """
        self.agent_name = agent_name
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")

        if not self.api_key:
            raise ValueError("Google API key is required. Set GOOGLE_API_KEY environment variable or pass api_key parameter.")

        # Configure Google Generative AI
        genai.configure(api_key=self.api_key)

        # Initialize the agent
        self.agent_executor = None
        self._initialize_agent()

    def _initialize_agent(self):
        """Initialize the LangChain agent with Google Gemini"""
        try:
            # Create the Gemini LLM
            model = genai.GenerativeModel('gemini-3.5-flash-lite')

            # Define tools for the agent
            tools = self._get_agent_tools()

            # Define prompt template
            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a helpful AI assistant for EUREKA company.
EUREKA is in the Agent Creation industry with the following constraints:
- Quarterly objectives: Gross margin >25%, Sales growth +15% QoQ
- Hard constraints: Minimum cash $50M, Debt limit $200M
- Escalation threshold: Amounts >$100M, legal risks, irresolvable conflicts
- Non-negotiable values: No selling below cost, comply with legal deadlines

Use the available tools to answer questions and validate proposals."""),
                ("placeholder", "{chat_history}"),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ])

            # Create the agent
            agent = create_tool_calling_agent(model, tools, prompt)

            # Create agent executor
            self.agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

            print(f"Managed Deep Agent '{self.agent_name}' initialized successfully!")
            print(f"Model: gemini-3.5-flash-lite")
            print(f"Tools available: {[tool.name for tool in tools]}")

        except Exception as e:
            print(f"Error initializing agent: {e}")
            raise

    def _get_agent_tools(self):
        """Define tools for the agent"""
        @tool
        def get_eureka_context() -> str:
            """Get the context and constraints for EUREKA company"""
            context = {
                "company_name": "EUREKA",
                "industry": "Agent Creation",
                "quarterly_objectives": {
                    "gross_margin": ">25%",
                    "sales_growth": "+15% QoQ"
                },
                "hard_constraints": {
                    "minimum_cash": "$50M",
                    "debt_limit": "$200M",
                    "max_project_cash_percentage": "30%"
                },
                "escalation_threshold": {
                    "amount": "$100M",
                    "legal_risk": True,
                    "irresolvable_conflicts": True
                },
                "non_negotiable_values": [
                    "No selling below cost",
                    "Comply with legal deadlines",
                    "Do not compromise minimum cash",
                    "Do not sign contracts without risk review"
                ]
            }
            return json.dumps(context, indent=2)

        @tool
        def validate_financial_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
            """Validate a financial proposal against EUREKA constraints"""
            # Implement validation logic
            validation = {
                "valid": True,
                "message": "Proposal validated",
                "issues": []
            }

            # Check gross margin
            if "gross_margin" in proposal and proposal["gross_margin"] < 25:
                validation["valid"] = False
                validation["issues"].append(f"Gross margin {proposal['gross_margin']}% below 25% target")

            # Check cash impact
            if "cash_impact" in proposal and proposal["cash_impact"] < 50_000_000:
                validation["valid"] = False
                validation["issues"].append(f"Cash impact ${proposal['cash_impact']} below $50M minimum")

            return validation

        return [get_eureka_context, validate_financial_proposal]

    def run(self, prompt: str) -> str:
        """
        Run the agent with a given prompt

        Args:
            prompt: The input prompt for the agent

        Returns:
            The agent's response
        """
        if not self.agent_executor:
            raise RuntimeError("Agent not initialized")

        try:
            response = self.agent_executor.invoke({"input": prompt})
            return response["output"]
        except Exception as e:
            print(f"Error running agent: {e}")
            raise

    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about the agent"""
        return {
            "agent_name": self.agent_name,
            "model": "gemini-3.5-flash-lite",
            "status": "initialized" if self.agent_executor else "not_initialized",
            "tools": [tool.name for tool in self._get_agent_tools()]
        }

def main():
    """Main function to demonstrate the Managed Deep Agent"""
    print("=== EUREKA Managed Deep Agent Setup (Simplified) ===")

    # Get API key from environment variable
    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable not set")
        print("Please set your Google API key as an environment variable")
        print("Example: export GOOGLE_API_KEY='your-api-key-here'")
        return

    try:
        # Initialize the agent
        agent = ManagedDeepAgentSimple(agent_name="my-agent", api_key=api_key)

        # Get agent info
        agent_info = agent.get_agent_info()
        print("\nAgent Information:")
        print(json.dumps(agent_info, indent=2))

        # Example usage
        print("\n=== Example Usage ===")
        example_prompt = "What is the quarterly objective for EUREKA?"
        print(f"Prompt: {example_prompt}")

        response = agent.run(example_prompt)
        print(f"Response: {response}")

        # Test tool usage
        print("\n=== Testing Tool Usage ===")
        test_prompt = "Please get the EUREKA context and validate a financial proposal with 20% gross margin and $45M cash impact."
        print(f"Prompt: {test_prompt}")

        response = agent.run(test_prompt)
        print(f"Response: {response}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()