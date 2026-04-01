# AutoGen + ShopSavvy

Microsoft AutoGen tools for product search and price comparison using the [ShopSavvy Data API](https://shopsavvy.com/data).

## Installation

```bash
pip install autogen-shopsavvy
```

## Setup

Get an API key at [shopsavvy.com/data](https://shopsavvy.com/data) and set it as an environment variable:

```bash
export SHOPSAVVY_API_KEY=ss_live_your_key_here
```

## Usage

```python
import os
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_shopsavvy import ProductSearchTool, PriceComparisonTool

model_client = OpenAIChatCompletionClient(model="gpt-4o")

agent = AssistantAgent(
    name="shopping_assistant",
    model_client=model_client,
    tools=[
        ProductSearchTool(api_key=os.environ["SHOPSAVVY_API_KEY"]),
        PriceComparisonTool(api_key=os.environ["SHOPSAVVY_API_KEY"]),
    ],
    system_message="You help users find the best deals on products.",
)
```

## Tools

### ProductSearchTool

Search for products by keyword or look up details by barcode/ASIN/URL.

```python
tool = ProductSearchTool(api_key="ss_live_your_key_here")

# Search by keyword
result = await tool.run_json({"query": "sony headphones", "limit": 5}, None)

# Look up by identifier
result = await tool.run_json({"query": "B09XS7JWHH"}, None)
```

### PriceComparisonTool

Get current offers from retailers for a product, with optional price history.

```python
tool = PriceComparisonTool(api_key="ss_live_your_key_here")

# Get current offers
result = await tool.run_json({"identifier": "B09XS7JWHH"}, None)

# Get price history
result = await tool.run_json({
    "identifier": "B09XS7JWHH",
    "include_history": True,
    "history_start": "2024-01-01",
    "history_end": "2024-06-01",
}, None)
```

## License

MIT
