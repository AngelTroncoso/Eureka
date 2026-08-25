#!/usr/bin/env python3
"""
Managed Deep Agent Configuration for EUREKA
Using google_genai:gemini-3.5-flash-lite
"""

import os
import json
from typing import Dict, Any, Optional

# Import required libraries
try:
    import google.generativeai as genai
    from langchain.agents import AgentType, initialize_agent
    from langchain.chains import LLMChain
    from langchain.prompts import PromptTemplate
    from langchain.memory import ConversationBufferMemory
    from langchain.agents import tool
except ImportError as e:
    print(f"Error importing required libraries: {e}")
    print("Please make sure you have installed: google-generativeai, langchain")
    exit(1)

class ManagedDeepAgent:
    """
    Managed Deep Agent for EUREKA using Google Gemini
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

        # Initialize memory
        self.memory = ConversationBufferMemory(memory_key="chat_history")

        # Initialize the agent
        self.agent = None
        self._initialize_agent()

    def _initialize_agent(self):
        """Initialize the LangChain agent with Google Gemini"""
        try:
            # Create the Gemini LLM
            model = genai.GenerativeModel('gemini-3.5-flash-lite')

            # Define tools for the agent
            tools = self._get_agent_tools()

            # Initialize the agent
            self.agent = initialize_agent(
                tools=tools,
                llm=model,
                agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
                verbose=True,
                memory=self.memory,
                handle_parsing_errors=True
            )

            print(f"Managed Deep Agent '{self.agent_name}' initialized successfully!")
            print(f"Model: gemini-3.5-flash-lite")
            print(f"Agent Type: {AgentType.ZERO_SHOT_REACT_DESCRIPTION}")

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
        if not self.agent:
            raise RuntimeError("Agent not initialized")

        try:
            response = self.agent.run(input=prompt)
            return response
        except Exception as e:
            print(f"Error running agent: {e}")
            raise

    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about the agent"""
        return {
            "agent_name": self.agent_name,
            "model": "gemini-3.5-flash-lite",
            "status": "initialized" if self.agent else "not_initialized",
            "tools": [tool.name for tool in self._get_agent_tools()]
        }

def main():
    """Main function to demonstrate the Managed Deep Agent"""
    print("=== EUREKA Managed Deep Agent Setup ===")

    # Get API key from environment variable
    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable not set")
        print("Please set your Google API key as an environment variable")
        return

    try:
        # Initialize the agent
        agent = ManagedDeepAgent(agent_name="my-agent", api_key=api_key)

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

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()