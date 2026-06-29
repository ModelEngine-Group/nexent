import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchTools } from "@/services/agentConfigService";
import { useMemo } from "react";
import { ToolGroup, ToolSubGroup } from "@/types/agentConfig";
import { TOOL_SOURCE_TYPES } from "@/const/agentConfig";

export function useToolList(options?: { enabled?: boolean; staleTime?: number }) {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["tools"],
		queryFn: async () => {
			const res = await fetchTools();
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch tools");
			}
			return res.data || [];
		},
		staleTime: options?.staleTime ?? 60_000,
		refetchOnMount: "always",
		refetchOnWindowFocus: true,
		enabled: options?.enabled ?? true,
	});

	const tools = query.data ?? [];

	const availableTools = useMemo(() => {
		return (tools as any[]).filter((tool) => tool.is_available !== false);
	}, [tools]);

	// Extract all unique labels from available tools (used by LabelManagementModal suggestions)
	const allLabels = useMemo(() => {
		const labelSet = new Set<string>();
		availableTools.forEach((tool: any) => {
			const labels = Array.isArray(tool.labels) ? tool.labels : [];
			labels.forEach((l: string) => labelSet.add(l));
		});
		return Array.from(labelSet).sort((a, b) => a.localeCompare(b));
	}, [availableTools]);

	// Grouped tools by source and usage
	const groupedTools = useMemo(() => {
		const groups: ToolGroup[] = [];
		const groupMap = new Map<string, any[]>();
	
		// Group by source and usage
		availableTools.forEach((tool) => {
		  let groupKey: string;
	
		  if (tool.source === TOOL_SOURCE_TYPES.MCP) {
			const usage = tool.usage || TOOL_SOURCE_TYPES.OTHER;
			groupKey = `mcp-${usage}`;
		  } else if (tool.source === TOOL_SOURCE_TYPES.LOCAL) {
			groupKey = TOOL_SOURCE_TYPES.LOCAL;
		  } else if (tool.source === TOOL_SOURCE_TYPES.LANGCHAIN) {
			groupKey = TOOL_SOURCE_TYPES.LANGCHAIN;
		  } else {
			groupKey = tool.source || TOOL_SOURCE_TYPES.OTHER;
		  }
	
		  if (!groupMap.has(groupKey)) {
			groupMap.set(groupKey, []);
		  }
		  groupMap.get(groupKey)!.push(tool);
		});
	
		// Convert to array and sort
		groupMap.forEach((tools, key) => {
		  const sortedTools = tools.sort((a, b) => {
			// Sort by creation time
			if (!a.create_time && !b.create_time) return 0;
			if (!a.create_time) return 1;
			if (!b.create_time) return -1;
			return a.create_time.localeCompare(b.create_time);
		  });
	
		  // Create secondary grouping for local tools
		  let subGroups: ToolSubGroup[] | undefined;
		  if (key === TOOL_SOURCE_TYPES.LOCAL) {
			const categoryMap = new Map<string, any[]>();
	
			sortedTools.forEach((tool) => {
			  const category =
				tool.category && tool.category.trim() !== ""
				  ? tool.category
				  : "toolPool.category.other";
			  if (!categoryMap.has(category)) {
				categoryMap.set(category, []);
			  }
			  categoryMap.get(category)!.push(tool);
			});
	
			subGroups = Array.from(categoryMap.entries())
			  .map(([category, categoryTools]) => ({
				key: category,
				label: category,
				tools: categoryTools.sort((a, b) => a.name.localeCompare(b.name)), // Sort by name alphabetically
			  }))
			  .sort((a, b) => {
				// Put "Other" category at the end
				const otherKey = "toolPool.category.other";
				if (a.key === otherKey) return 1;
				if (b.key === otherKey) return -1;
				return a.label.localeCompare(b.label); // Sort other categories alphabetically
			  });
		  }
	
		  groups.push({
			key,
			label: key.startsWith("mcp-")
			  ? key.replace("mcp-", "")
			  : key === TOOL_SOURCE_TYPES.LOCAL
			  ? "toolPool.group.local"
			  : key === TOOL_SOURCE_TYPES.LANGCHAIN
			  ? "toolPool.group.langchain"
			  : key,
			tools: sortedTools,
			subGroups,
		  });
		});
	
		// Sort by priority: local > langchain > mcp groups
		return groups.sort((a, b) => {
		  const getPriority = (key: string) => {
			if (key === TOOL_SOURCE_TYPES.LOCAL) return 1;
			if (key === TOOL_SOURCE_TYPES.LANGCHAIN) return 2;
			if (key.startsWith("mcp-")) return 3;
			return 4;
		  };
		  return getPriority(a.key) - getPriority(b.key);
		});
	  }, [availableTools]);

	return {
		...query,
		tools,
		availableTools,
		groupedTools,
		allLabels,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["tools"] }),
	};
}

