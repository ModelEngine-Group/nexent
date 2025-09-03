"use client"

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Modal, Spin, message, Typography } from 'antd'
import { RobotOutlined, ToolOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { fetchAgentCallRelationship } from '@/services/agentConfigService'
import Tree from 'react-d3-tree';

const { Text } = Typography

interface Tool {
  tool_id: string
  name: string
  type: string
}

interface SubAgent {
  agent_id: string
  name: string
  tools: Tool[]
  sub_agents: SubAgent[]
  depth?: number
}

interface AgentCallRelationship {
  agent_id: string
  name: string
  tools: Tool[]
  sub_agents: SubAgent[]
}

interface AgentCallRelationshipModalProps {
  visible: boolean
  onClose: () => void
  agentId: number
  agentName: string
}

/** Consistent with custom node visual dimensions (convenient for line endings at edges) */
const NODE_W = 140;
const NODE_H = 60;


const AGENT_W = 160;                  
const AGENT_H = 56;                    
const TOOL_SIZE = 86;                 
const TOOL_TEETH = 10;                 
const TOOL_TEETH_DEPTH_RATIO = 0.085;  

const MAX_TOOL_NAME_CHARS = 10;       

const TREE_DEPTH_FACTOR = 120;         
const TREE_SEP_SIB = 1.15;
const TREE_SEP_NON = 1.35;


function truncateByCodePoints(s: string, max: number) {
  const arr = Array.from(s);
  return arr.length > max ? arr.slice(0, max).join('') + '…' : s;
}

// Enhanced color configuration with modern palette
const themeConfig = {
  colors: {
    node: {
      main: '#1a1a2e',
      levels: {
        1: '#16213e',
        2: '#0f3460', 
        3: '#533483',
        4: '#7209b7'
      },
      tools: {
        1: '#ff6b6b',
        2: '#4ecdc4',
        3: '#45b7d1',
        4: '#96ceb4'
      }
    }
  }
} as const;

// Get node color
const getNodeColor = (type: string, depth: number = 0) => {
  const { colors } = themeConfig;
  
  switch (type) {
    case 'main':
      return colors.node.main;
    case 'sub':
      return colors.node.levels[depth as keyof typeof colors.node.levels] || colors.node.levels[1];
    case 'tool':
      return colors.node.tools[depth as keyof typeof colors.node.tools] || colors.node.tools[1];
    default:
      return colors.node.main;
  }
};

// Custom node - center aligned, unified font style
const CustomNode = ({ nodeDatum }: any) => {
  const isAgent = nodeDatum.type === 'main' || nodeDatum.type === 'sub';
  const color = getNodeColor(nodeDatum.type, nodeDatum.depth);
  const icon = isAgent ? <RobotOutlined /> : <ToolOutlined />;


  const rawName: string = nodeDatum.name || '';
  const displayName: string = !isAgent
    ? truncateByCodePoints(rawName, MAX_TOOL_NAME_CHARS)
    : rawName;


  const fontSize = isAgent ? '14px' : '12px';
  const fontWeight = isAgent ? '600' : '500';


  const nodeWidth  = isAgent ? AGENT_W : TOOL_SIZE;
  const nodeHeight = isAgent ? AGENT_H : TOOL_SIZE;

  // Select different shapes based on node type with enhanced styling
  const renderNodeShape = () => {
    if (isAgent) {
      // Agent nodes use rounded rectangle with enhanced styling
      return (
        <rect
          width={nodeWidth}
          height={nodeHeight}
          rx={14}
          ry={14}
          fill={color}
          stroke={`${color}80`}
          strokeWidth={1.5}
          style={{ 
            transition: 'all 0.3s ease',
            filter: 'drop-shadow(0 3px 6px rgba(0,0,0,0.12))'
          }}
        />
      );
    } else {

      const cx = nodeWidth / 2;
      const cy = nodeHeight / 2;
      const outerRadius = nodeWidth / 2 - 2;
      const teethDepth = Math.max(outerRadius * TOOL_TEETH_DEPTH_RATIO, 3.5);

      const d: string[] = [];
      for (let i = 0; i < TOOL_TEETH * 2; i++) {
        const angle = (i * Math.PI) / TOOL_TEETH; 
        const r = i % 2 === 0 ? outerRadius : outerRadius - teethDepth;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        d.push(`${i === 0 ? 'M' : 'L'} ${x} ${y}`);
      }
      d.push('Z');

      return (
        <path
          d={d.join(' ')}
          fill={color}
          stroke={`${color}80`}
          strokeWidth={1.5}
          style={{ 
            transition: 'all 0.3s ease',
            filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.10))'
          }}
        />
      );
    }
  };

  return (
    <g transform={`translate(-${nodeWidth / 2}, -${nodeHeight / 2})`}>
      {renderNodeShape()}
      
      <foreignObject
        x={0}
        y={0}
        width={nodeWidth}
        height={nodeHeight}
        style={{ overflow: 'hidden', borderRadius: isAgent ? 14 : nodeWidth / 2 }}
      >
        <div
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px',
            padding: isAgent ? '0 16px' : '0 12px',
            fontSize,
            color: isAgent ? '#ffffff' : '#1e293b',
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
            fontWeight,
            textAlign: 'center',
            lineHeight: 1,
            userSelect: 'none',
            letterSpacing: '0.02em',
            whiteSpace: 'nowrap',
          }}
        >
          <span style={{ 
            display: 'inline-flex',
            width: isAgent ? '18px' : '16px',
            height: isAgent ? '18px' : '16px',
            alignItems: 'center',
            justifyContent: 'center',
            transform: 'translateY(-0.5px)',
            flex: '0 0 auto'
          }}>
            {icon}
          </span>
          <span
            style={{
              display: 'inline-block',
              maxWidth: '100%',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
            title={rawName}
          >
            {displayName}
          </span>
        </div>
      </foreignObject>
    </g>
  );
};

/** Make lines end at node edges: from parent rectangle bottom edge to child rectangle top edge (vertical layout) */
const customPathFunc = (linkData: any, orientation: 'vertical' | 'horizontal') => {
  const { source, target } = linkData;

  if (orientation === 'horizontal') {
    const srcX = source.x + NODE_W / 2;
    const srcY = source.y;
    const tgtX = target.x - NODE_W / 2;
    const tgtY = target.y;
    const midX = (srcX + tgtX) / 2;
    return `M ${srcX} ${srcY} L ${midX} ${srcY} L ${midX} ${tgtY} L ${tgtX} ${tgtY}`;
  }

  // Vertical layout: from parent node bottom edge -> middle break point -> child node top edge
  const srcX = source.x;
  const srcY = source.y + NODE_H / 2;
  const tgtX = target.x;
  const tgtY = target.y - NODE_H / 2;
  const midY = (srcY + tgtY) / 2;
  return `M ${srcX} ${srcY} L ${srcX} ${midY} L ${tgtX} ${midY} L ${tgtX} ${tgtY}`;
};

// Type definition
interface TreeNodeDatum {
  name: string;
  type?: string;
  color?: string;
  count?: string;
  children?: TreeNodeDatum[];
  depth?: number;
  attributes?: { toolType?: string };
}

declare module 'react-d3-tree';

export default function AgentCallRelationshipModal({
  visible,
  onClose,
  agentId,
  agentName
}: AgentCallRelationshipModalProps) {
  const { t } = useTranslation('common')
  const [loading, setLoading] = useState(false)
  const [relationshipData, setRelationshipData] = useState<AgentCallRelationship | null>(null)

  const treeWrapRef = useRef<HTMLDivElement>(null);
  const [translate, setTranslate] = useState<{ x: number; y: number }>({ x: 800, y: 120 });

  useEffect(() => {
    if (visible && agentId) {
      loadCallRelationship()
    }
  }, [visible, agentId])

  useEffect(() => {
    if (treeWrapRef.current && visible) {
      const { clientWidth } = treeWrapRef.current;
      const x = Math.round(clientWidth / 2);
      const y = 100;
      setTranslate({ x, y });
    }
  }, [visible]);

  const loadCallRelationship = async () => {
    setLoading(true)
    try {
      const result = await fetchAgentCallRelationship(agentId)
      if (result.success) {
        setRelationshipData(result.data)
      } else {
        message.error(result.message || '获取调用关系失败')
      }
    } catch (error) {
      console.error('Failed to get the agent call relationship:', error)
      message.error('Failed to get the agent call relationship')
    } finally {
      setLoading(false)
    }
  }

  // Generate tree data (using recursive method)
  const generateTreeData = useCallback((data: AgentCallRelationship): TreeNodeDatum => {
    const centerX = 600;
    const startY = 50;
    const levelHeight = 160;
    const agentSpacing = 240;
    const toolSpacing = 160;

    // Recursively generate child nodes
    const generateSubNodes = (subAgents: SubAgent[], depth: number, parentX: number, parentY: number): TreeNodeDatum[] => {
      
      return subAgents.map((subAgent, index) => {
        const x = parentX + (index - (subAgents.length - 1) / 2) * agentSpacing;
        const y = parentY + levelHeight;
        
        const subAgentNode: TreeNodeDatum = {
          name: subAgent.name,
          type: 'sub',
          depth: subAgent.depth || depth,
          color: getNodeColor('sub', subAgent.depth || depth),
          children: []
        };

        // Add tool nodes
        if (subAgent.tools && subAgent.tools.length > 0) {
          const toolsPerRow = Math.min(2, subAgent.tools.length);
          const toolStartX = x - (toolsPerRow - 1) * toolSpacing / 2;

          subAgent.tools.forEach((tool, toolIndex) => {
            const row = Math.floor(toolIndex / toolsPerRow);
            const col = toolIndex % toolsPerRow;
            const toolX = toolStartX + col * toolSpacing;
            const toolY = y + levelHeight + row * 56;

            subAgentNode.children!.push({
              name: tool.name,
              type: 'tool',
              depth: (subAgent.depth || depth) + 1,
              color: getNodeColor('tool', (subAgent.depth || depth) + 1),
              attributes: { toolType: tool.type },
              children: []
            });
          });
        }

        // Recursively process deeper sub-agents
        if (subAgent.sub_agents && subAgent.sub_agents.length > 0) {
          const deepSubNodes = generateSubNodes(subAgent.sub_agents, depth + 1, x, y);
          subAgentNode.children!.push(...deepSubNodes);
        }

        return subAgentNode;
      });
    };

    const treeData: TreeNodeDatum = {
      name: data.name,
      type: 'main',
      depth: 0,
      color: getNodeColor('main', 0),
      children: []
    };

    // Add main agent tools
    if (data.tools && data.tools.length > 0) {
      const toolsPerRow = Math.min(3, data.tools.length);
      const startX2 = centerX - (toolsPerRow - 1) * toolSpacing / 2;

      data.tools.forEach((tool, index) => {
        const row = Math.floor(index / toolsPerRow);
        const col = index % toolsPerRow;
        const x = startX2 + col * toolSpacing;
        const y = startY + levelHeight + row * 56;

        treeData.children!.push({
          name: tool.name,
          type: 'tool',
          depth: 1,
          color: getNodeColor('tool', 1),
          attributes: { toolType: tool.type },
          children: []
        });
      });
    }

    // Recursively add sub-agents
    if (data.sub_agents && data.sub_agents.length > 0) {
      const subNodes = generateSubNodes(data.sub_agents, 1, centerX, startY);
      treeData.children!.push(...subNodes);
    }

    return treeData;
  }, []);

  return (
    <>
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>{t('agentCallRelationship.title')}</span>
            <Text type="secondary" style={{ fontSize: '14px', fontWeight: 'normal' }}>
              {agentName}
            </Text>
          </div>
        }
        open={visible}
        onCancel={onClose}
        footer={null}
        width={1800}
        destroyOnClose
        centered
        style={{ top: 20 }}
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: '40px' }}>
            <Spin size="large" />
            <div style={{ marginTop: '16px' }}>
              <Text type="secondary">{t('agentCallRelationship.loading')}</Text>
            </div>
          </div>
        ) : relationshipData ? (
          <div>
            <div style={{ marginBottom: '16px' }}>
              <Text type="secondary">
                {t('agentCallRelationship.description', { name: relationshipData.name })}
              </Text>
            </div>
            <div
              ref={treeWrapRef}
              style={{
                height: '820px',
                width: '100%',
                background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 50%, #cbd5e1 100%)',
                borderRadius: 20,
                overflow: 'hidden',
                padding: 0,
                boxShadow: '0 20px 60px rgba(0,0,0,0.15), 0 8px 25px rgba(0,0,0,0.1)',
                position: 'relative'
              }}
            >
              <Tree
                data={generateTreeData(relationshipData)}
                orientation="vertical"
                /** Custom path: lines end at node edges, no longer insert into interior */
                pathFunc={(linkData: any) => customPathFunc(linkData, 'vertical')}
                translate={translate}
                renderCustomNodeElement={CustomNode}
                depthFactor={TREE_DEPTH_FACTOR}
                separation={{ siblings: TREE_SEP_SIB, nonSiblings: TREE_SEP_NON }}
                nodeSize={{ x: NODE_W, y: NODE_H }}
                pathClassFunc={() => 'connection'}
                zoomable={true}
                scaleExtent={{ min: 0.8, max: 1.4 }}
                collapsible={false}
                initialDepth={undefined}
                enableLegacyTransitions={true}
                transitionDuration={250}
              />
            </div>
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '40px' }}>
            <Text type="secondary">{t('agentCallRelationship.noData')}</Text>
          </div>
        )}
      </Modal>

      <style jsx>{`
         .connection {
           stroke: #64748b;
           stroke-width: 2;
           stroke-opacity: 0.85;
           fill: none;
           stroke-linecap: round;
           stroke-linejoin: round;
           transition: all 0.25s ease;
         }
         
         .connection:hover {
           stroke: #475569;
           stroke-opacity: 1;
           stroke-width: 2.4;
         }
         
         /* Enhanced node hover effects */
         :global(.rd3t-node) {
           transition: filter 0.2s ease;
         }
         
         :global(.rd3t-node:hover) {
           filter: brightness(1.04) drop-shadow(0 4px 10px rgba(0,0,0,0.16));
         }
         
         /* Double insurance: force hide library's built-in labels */
         :global(.rd3t-label),
         :global(.rd3t-label__title),
         :global(.rd3t-label__attributes) {
           display: none !important;
           opacity: 0 !important;
           visibility: hidden !important;
         }
         
         /* Enhanced SVG rendering */
         :global(svg) {
           filter: drop-shadow(0 1px 3px rgba(0,0,0,0.08));
         }
         
         :global(svg text) {
           text-rendering: optimizeLegibility !important;
         }
       `}</style>
    </>
  );
}
