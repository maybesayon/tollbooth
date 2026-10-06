from tollbooth.domain import Provider
from tollbooth.providers.anthropic import AnthropicAdapter
from tollbooth.providers.openai import OpenAIAdapter

OPENAI = OpenAIAdapter()
ANTHROPIC = AnthropicAdapter()
ADAPTERS = {Provider.OPENAI: OPENAI, Provider.ANTHROPIC: ANTHROPIC}
