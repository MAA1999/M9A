---
index: 7
icon: carbon:ibm-watsonx-code-assistant-for-z-refactor
---
# Project Refactoring

## Image/Model

When modifying, ensure that no nodes using the Image/Model are overlooked.

> [!TIP]
>
> Make good use of global search.

## Pipeline

### Other Nodes

Next, refactor other nodes based on their specific purposes.

#### Standardizing Node Names

If the goal is merely to standardize node names, use VSCode's global search and replace functionality.  
However, ensure that replacements include double quotes to avoid modifying other nodes containing the node name.

#### Simplifying Task Flows and Reducing Coupling

First, read [Node Connections](./pipeline.md#node-connections) and refactor towards adhering to connection principles.

Some nodes can be moved to the `interrupt` of the ancestor node of the current node.  
After moving, remove unnecessary `next` nodes to avoid continuing the main task chain in the `interrupt`, which could cause errors in subsequent tasks and return to the ancestor node.

#### Merging Nodes with Similar Functions

If multiple nodes perform the same function, consider merging them into a single node.

Steps:

1. Before merging, check whether there are unrelated nodes in the `next` of the node. If so, separate them first.
2. During merging, all nodes should adopt the same standardized name.
3. After merging, check whether the node's position in all tasks is correct. For example, ensure nodes that should be in the `interrupt` are not in the main task chain's `next` section.
