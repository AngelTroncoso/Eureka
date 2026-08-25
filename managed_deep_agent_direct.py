#!/usr/bin/env python3
"""
Managed Deep Agent Configuration for EUREKA - Direct Gemini Version
Using google_genai:gemini-3.5-flash-lite directly without LangChain agents
"""

import os
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import required libraries
try:
    import google.generativeai as genai
    from langsmith import traceable
except ImportError as e:
    print(f"Error importing required libraries: {e}")
    print("Please make sure you have installed: google-generativeai, langsmith")
    exit(1)

class ManagedDeepAgentDirect:
    """
    Direct Managed Deep Agent for EUREKA using Google Gemini
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

        # Initialize the model
        self.model = genai.GenerativeModel('gemini-3.5-flash-lite')

        # Initialize chat session
        self.chat = self.model.start_chat(history=[])

        print(f"Managed Deep Agent '{self.agent_name}' initialized successfully!")
        print(f"Model: gemini-3.5-flash-lite")
        print(f"Status: Ready for direct interaction")

    @traceable(name="get_eureka_context")
    def get_eureka_context(self) -> str:
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

    @traceable(name="validate_financial_proposal")
    def validate_financial_proposal(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
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

    @traceable(name="managed_deep_agent_direct")
    def run(self, prompt: str) -> str:
        """
        Run the agent with a given prompt

        Args:
            prompt: The input prompt for the agent

        Returns:
            The agent's response
        """
        try:
            # Add EUREKA context to the prompt
            full_prompt = f"""You are a helpful AI assistant for EUREKA company.
EUREKA is in the Agent Creation industry with the following constraints:
- Quarterly objectives: Gross margin >25%, Sales growth +15% QoQ
- Hard constraints: Minimum cash $50M, Debt limit $200M
- Escalation threshold: Amounts >$100M, legal risks, irresolvable conflicts
- Non-negotiable values: No selling below cost, comply with legal deadlines

User question: {prompt}"""

            response = self.chat.send_message(full_prompt)
            return response.text
        except Exception as e:
            print(f"Error running agent: {e}")
            raise

    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about the agent"""
        return {
            "agent_name": self.agent_name,
            "model": "gemini-3.5-flash-lite",
            "status": "initialized",
            "capabilities": [
                "Direct interaction with Gemini model",
                "EUREKA context integration",
                "Financial proposal validation"
            ]
        }

def main():
    """Main function to demonstrate the Managed Deep Agent"""
    print("=== EUREKA Managed Deep Agent Setup (Direct) ===")

    # Get API key from environment variable
    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable not set")
        print("Please configure your API keys in the .env file:")
        print("1. Open the .env file in this directory")
        print("2. Replace 'pega-aqui-tu-google-api-key' with your actual Google API key")
        print("3. Save the file and run the script again")
        print("\nExample .env content:")
        print("GOOGLE_API_KEY='your-actual-api-key-here'")
        print("LANGCHAIN_API_KEY='your-langchain-api-key-here'")
        return

    try:
        # Initialize the agent
        agent = ManagedDeepAgentDirect(agent_name="my-agent", api_key=api_key)

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

        # Test context retrieval
        print("\n=== EUREKA Context ===")
        context = agent.get_eureka_context()
        print(context)

        # Test validation
        print("\n=== Financial Proposal Validation ===")
        test_proposal = {
            "gross_margin": 20,
            "cash_impact": 45_000_000
        }
        validation = agent.validate_financial_proposal(test_proposal)
        print("Validation result:")
        print(json.dumps(validation, indent=2))

        # Test complex query
        print("\n=== Complex Query ===")
        complex_prompt = "Analyze this financial proposal and suggest improvements considering EUREKA's constraints."
        response = agent.run(complex_prompt)
        print(f"Response: {response}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()