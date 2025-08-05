import { useRef, useEffect, useState } from "react"
import { ScrollArea } from "@/components/ui/scrollArea"
import { ChatMessageType, TaskMessageType } from "@/types/chat"
import { MarkdownRenderer } from '@/components/ui/markdownRenderer'
import { Globe, Search, Zap, Bot, Code, FileText, HelpCircle, ChevronRight, Wrench } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useChatTaskMessage } from "@/hooks/useChatTaskMessage"
import { useTranslation } from "react-i18next"

// Icon mapping dictionary - map strings to corresponding icon components
const iconMap: Record<string, React.ReactNode> = {
  "search": <Search size={16} className="mr-2" color="#4b5563" />,
  "bot": <Bot size={16} className="mr-2" color="#4b5563" />,
  "code": <Code size={16} className="mr-2" color="#4b5563" />,
  "file": <FileText size={16} className="mr-2" color="#4b5563" />,
  "globe": <Globe size={16} className="mr-2" color="#4b5563" />,
  "zap": <Zap size={16} className="mr-2" color="#4b5563" />,
  "knowledge": <FileText size={16} className="mr-2" color="#4b5563" />,
  "default": <Wrench size={16} className="mr-2" color="#4b5563" /> // Default icon
};

// Define the type for card items
interface CardItem {
  icon?: string;
  text: string;
  [key: string]: any; // Allow other properties
}

// Define the interface for message handlers to improve extensibility
interface MessageHandler {
  canHandle: (message: any) => boolean;
  render: (message: any, t: (key: string, options?: any) => string) => React.ReactNode;
}

// Define the handlers for different types of messages to improve extensibility
const messageHandlers: MessageHandler[] = [
  // Processing type processor - thinking, code generation, code execution
  {
    canHandle: (message) => 
      message.type === "agent_new_run" || 
      message.type === "generating_code" ||
      message.type === "executing" ||
      message.type === "model_output_thinking" ||
      message.type === "model_output_deep_thinking",
    render: (message, _t) => (
        <div style={{
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
          fontSize: "0.875rem",
          lineHeight: 1.5,
          color: "#6b7280",
          fontWeight: 500,
          borderRadius: "0.25rem",
          paddingTop: "0.5rem"
        }}>
          <span>{message.content}</span>
        </div>
      )
  },
  
  // Add search_content_placeholder type processor - for history records
  {
    canHandle: (message) => message.type === "search_content_placeholder",
    render: (message, t) => {
      // Find search results in the message context
      const messageContainer = message._messageContainer;
      if (!messageContainer || !messageContainer.search || messageContainer.search.length === 0) {
        return null;
      }
      
      // Build the content for displaying search results
      const searchResults = messageContainer.search;
      
      // deduplication logic - based on the combination of URL and filename
      const uniqueSearchResults = searchResults.filter((result: any, index: number, array: any[]) => {
        const currentKey = `${result.url || ''}-${result.filename || ''}-${result.title || ''}`;
        return array.findIndex((item: any) => {
          const itemKey = `${item.url || ''}-${item.filename || ''}-${item.title || ''}`;
          return itemKey === currentKey;
        }) === index;
      });
      
      // Process website information for display
      const siteInfos = uniqueSearchResults.map((result: any) => {
        const pageUrl = result.url || "";
        const filename = result.filename || "";
        const sourceType = result.source_type || "";
        let domain = t('taskWindow.unknownSource');
        let displayName = t('taskWindow.unknownSource');
        let baseUrl = "";
        let faviconUrl = "";
        let useDefaultIcon = false;
        let isKnowledgeBase = false;
        let canClick = true; // whether to allow click to jump
        
        // first judge based on source_type
        if (sourceType === "file") {
          isKnowledgeBase = true;
          displayName = filename || result.title || t('taskWindow.knowledgeFile');
          useDefaultIcon = true;
          canClick = false; // file type does not allow jump
        }
        // if there is no source_type, judge based on filename (compatibility processing)
        else if (filename) {
          isKnowledgeBase = true;
          displayName = filename;
          useDefaultIcon = true;
          canClick = false; // file type does not allow jump
        }
        // handle webpage link
        else if (pageUrl && pageUrl !== "#") {
          try {
            const parsedUrl = new URL(pageUrl);
            baseUrl = `${parsedUrl.protocol}//${parsedUrl.host}`;
            domain = parsedUrl.hostname;
            
            // Process the domain, remove the www prefix and com/cn etc. suffix
            displayName = domain
              .replace(/^www\./, '') // Remove the www. prefix
              .replace(/\.(com|cn|org|net|io|gov|edu|co|info|biz|xyz)(\.[a-z]{2})?$/, ''); // Remove common suffixes
            
            // If the processing is empty, use the original domain
            if (!displayName) {
              displayName = domain;
            }
            
            faviconUrl = `${baseUrl}/favicon.ico`;
            canClick = true;
          } catch (e) {
            console.error(t('taskWindow.urlParseError'), e);
            useDefaultIcon = true;
            canClick = false;
          }
        } else {
          useDefaultIcon = true;
          canClick = false;
        }
        
        return { 
          domain, 
          displayName, 
          faviconUrl, 
          url: pageUrl, 
          useDefaultIcon, 
          isKnowledgeBase,
          filename,
          canClick
        };
      });
      
      // Render the search result information bar
      return (
        <div style={{
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
          fontSize: "0.875rem",
          lineHeight: 1.5,
        }}>
          {/* Display multiple source websites in a single line */}
          <div style={{
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
            marginBottom: "0.25rem"
          }}>
            {/* "Reading" label - a single line */}
            <div style={{
              fontSize: "0.875rem",
              color: "#6b7280",
              fontWeight: 500,
              paddingTop: "0.5rem"
            }}>
              {t('taskWindow.readingSearchResults')}
            </div>
            
            {/* Website icon and domain list - a new line */}
            <div style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "0.5rem"
            }}>
              {siteInfos.map((site: any, index: number) => (
                <div 
                  key={index}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: "0.25rem 0.5rem",
                    backgroundColor: "#f9fafb",
                    borderRadius: "0.25rem",
                    fontSize: "0.75rem",
                    color: "#4b5563",
                    border: "1px solid #e5e7eb",
                    cursor: site.canClick ? "pointer" : "default",
                    transition: site.canClick ? "background-color 0.2s" : "none"
                  }}
                  onClick={() => {
                    if (site.canClick && site.url) {
                      window.open(site.url, "_blank", "noopener,noreferrer");
                    }
                  }}
                  onMouseEnter={(e) => {
                    if (site.canClick) {
                      e.currentTarget.style.backgroundColor = "#f3f4f6";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (site.canClick) {
                      e.currentTarget.style.backgroundColor = "#f9fafb";
                    }
                  }}
                  title={site.canClick ? t('taskWindow.visit', { domain: site.domain }) : site.filename || site.displayName}
                >
                  {site.isKnowledgeBase ? (
                    <FileText 
                      size={16} 
                      className="mr-2"
                      color="#6b7280"
                    />
                  ) : site.useDefaultIcon ? (
                    <Globe 
                      size={16} 
                      className="mr-2"
                      color="#6b7280"
                    />
                  ) : (
                    <img 
                      src={site.faviconUrl} 
                      alt={site.domain}
                      style={{
                        width: "16px",
                        height: "16px",
                        marginRight: "0.5rem",
                        borderRadius: "2px"
                      }}
                      onError={(e) => {
                        // If the icon fails to load, replace it with a React component
                        const imgElement = e.target as HTMLImageElement;
                        // Mark the element to prevent duplicate onError triggers
                        imgElement.style.display = 'none';
                        // Get the parent element
                        const parent = imgElement.parentElement;
                        if (parent) {
                          // Create a placeholder div, as the container of the Globe component
                          const placeholder = document.createElement('div');
                          placeholder.style.marginRight = '0.5rem';
                          placeholder.style.display = 'inline-flex';
                          placeholder.style.alignItems = 'center';
                          placeholder.style.justifyContent = 'center';
                          placeholder.style.width = '16px';
                          placeholder.style.height = '16px';
                          // Insert it before the img
                          parent.insertBefore(placeholder, imgElement);
                          // Render the Globe icon to this element (this can only be approximated using native methods)
                          placeholder.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>';
                        }
                      }}
                    />
                  )}
                  <span>{site.displayName}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      );
    }
  },
  
  // card type processor - display cards with icons
  {
    canHandle: (message) => message.type === "card",
    render: (message, t) => {
      let cardItems: CardItem[] = [];
      
      try {
        // Parse the card content
        if (typeof message.content === 'string') {
          cardItems = JSON.parse(message.content);
        } else if (Array.isArray(message.content)) {
          cardItems = message.content;
        }
      } catch (error) {
        console.error(t('taskWindow.parseCardError'), error);
        return (
          <div style={{color: "red", padding: "8px"}}>
            {t('taskWindow.cannotParseCard')}
          </div>
        );
      }
      
      if (!cardItems || cardItems.length === 0) {
        return null;
      }
      
      return (
        <div style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          marginTop: "0.25rem"
        }}>
          {cardItems.map((card: CardItem, index: number) => (
            <div
              key={index}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "0.25rem 0.5rem",
                backgroundColor: "#f9fafb",
                borderRadius: "0.25rem",
                fontSize: "0.7rem",
                color: "#4b5563",
                border: "1px solid #e5e7eb",
                fontWeight: 500
              }}
            >
              {/* Get the corresponding icon component from the dictionary based on the icon name */}
              {card.icon && iconMap[card.icon] ? iconMap[card.icon] : iconMap["default"]}
              <span>{card.text}</span>
            </div>
          ))}
        </div>
      );
    }
  },
  
  // search_content type processor - search results
  {
    canHandle: (message) => {
      const isSearchContent = message.type === "search_content";
      return isSearchContent;
    },
    render: (message, t) => {
      
      // Extract search results from the content
      let searchResults = [];
      const content = message.content || "";
      
      try {
        // Try to parse the JSON content
        if (typeof content === 'string') {
          // Parse the JSON string
          const parsedContent = JSON.parse(content);
          
          // Check if it is an array
          if (Array.isArray(parsedContent)) {
            searchResults = parsedContent;
          } else {
            // If it is not an array but an object, it may be a single result
            searchResults = [parsedContent];
          }
        } else if (Array.isArray(content)) {
          // If it is already an array, use it directly
          searchResults = content;
        }
      } catch (error: any) {
        console.error(t('taskWindow.parseSearchError'), error);
        return (
          <div style={{color: "red", padding: "8px"}}>
            {t('taskWindow.cannotParseSearch', { message: error.message })}
          </div>
        );
      }
      
      // If there are no search results, display an empty message
      if (!searchResults || searchResults.length === 0) {
        return (
          <div style={{padding: "8px", color: "#6b7280"}}>
            {t('taskWindow.noSearchResults')}
          </div>
        );
      }
      
      // deduplication logic - based on the combination of URL and filename
      const uniqueSearchResults = searchResults.filter((result: any, index: number, array: any[]) => {
        const currentKey = `${result.url || ''}-${result.filename || ''}-${result.title || ''}`;
        return array.findIndex((item: any) => {
          const itemKey = `${item.url || ''}-${item.filename || ''}-${item.title || ''}`;
          return itemKey === currentKey;
        }) === index;
      });
      
      // Process website information for display
      const siteInfos = uniqueSearchResults.map((result: any) => {
        const pageUrl = result.url || "";
        const filename = result.filename || "";
        const sourceType = result.source_type || "";
        let domain = t('taskWindow.unknownSource');
        let displayName = t('taskWindow.unknownSource');
        let baseUrl = "";
        let faviconUrl = "";
        let useDefaultIcon = false;
        let isKnowledgeBase = false;
        let canClick = true; // whether to allow click to jump
        
        // first judge based on source_type
        if (sourceType === "file") {
          isKnowledgeBase = true;
          displayName = filename || result.title || t('taskWindow.knowledgeFile');
          useDefaultIcon = true;
          canClick = false; // file type does not allow jump
        }
        // if there is no source_type, judge based on filename (compatibility processing)
        else if (filename) {
          isKnowledgeBase = true;
          displayName = filename;
          useDefaultIcon = true;
          canClick = false; // file type does not allow jump
        }
        // handle webpage link
        else if (pageUrl && pageUrl !== "#") {
          try {
            const parsedUrl = new URL(pageUrl);
            baseUrl = `${parsedUrl.protocol}//${parsedUrl.host}`;
            domain = parsedUrl.hostname;
            
            // Process the domain, remove the www prefix and com/cn etc. suffix
            displayName = domain
              .replace(/^www\./, '') // Remove the www. prefix
              .replace(/\.(com|cn|org|net|io|gov|edu|co|info|biz|xyz)(\.[a-z]{2})?$/, ''); // Remove common suffixes
            
            // If the processing is empty, use the original domain
            if (!displayName) {
              displayName = domain;
            }
            
            faviconUrl = `${baseUrl}/favicon.ico`;
            canClick = true;
          } catch (e) {
            console.error(t('taskWindow.urlParseError'), e);
            useDefaultIcon = true;
            canClick = false;
          }
        } else {
          useDefaultIcon = true;
          canClick = false;
        }
        
        return { 
          domain, 
          displayName, 
          faviconUrl, 
          url: pageUrl, 
          useDefaultIcon, 
          isKnowledgeBase,
          filename,
          canClick
        };
      });
      
      // Render the search result information bar
      return (
        <div style={{
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
          fontSize: "0.875rem",
          lineHeight: 1.5,
        }}>
          {/* Display multiple source websites in a single line */}
          <div style={{
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
            marginBottom: "0.25rem"
          }}>
            {/* "Reading search results" label - a single line */}
            <div style={{
              fontSize: "0.875rem",
              color: "#6b7280",
              fontWeight: 500,
              paddingTop: "0.5rem"
            }}>
              {t('taskWindow.readingSearchResults')}
            </div>
            
            {/* Website icon and domain list - a new line */}
            <div style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "0.5rem"
            }}>
              {siteInfos.map((site: any, index: number) => (
                <div 
                  key={index}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: "0.25rem 0.5rem",
                    backgroundColor: "#f9fafb",
                    borderRadius: "0.25rem",
                    fontSize: "0.75rem",
                    color: "#4b5563",
                    border: "1px solid #e5e7eb",
                    cursor: site.canClick ? "pointer" : "default",
                    transition: site.canClick ? "background-color 0.2s" : "none"
                  }}
                  onClick={() => {
                    if (site.canClick && site.url) {
                      window.open(site.url, "_blank", "noopener,noreferrer");
                    }
                  }}
                  onMouseEnter={(e) => {
                    if (site.canClick) {
                      e.currentTarget.style.backgroundColor = "#f3f4f6";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (site.canClick) {
                      e.currentTarget.style.backgroundColor = "#f9fafb";
                    }
                  }}
                  title={site.canClick ? t('taskWindow.visit', { domain: site.domain }) : site.filename || site.displayName}
                >
                  {site.isKnowledgeBase ? (
                    <FileText 
                      size={16} 
                      className="mr-2"
                      color="#6b7280"
                    />
                  ) : site.useDefaultIcon ? (
                    <Globe 
                      size={16} 
                      className="mr-2"
                      color="#6b7280"
                    />
                  ) : (
                    <img 
                      src={site.faviconUrl} 
                      alt={site.domain}
                      style={{
                        width: "16px",
                        height: "16px",
                        marginRight: "0.5rem",
                        borderRadius: "2px"
                      }}
                      onError={(e) => {
                        // If the icon fails to load, replace it with a React component
                        const imgElement = e.target as HTMLImageElement;
                        // Mark the element to prevent duplicate onError triggers
                        imgElement.style.display = 'none';
                        // Get the parent element
                        const parent = imgElement.parentElement;
                        if (parent) {
                          // Create a placeholder div, as the container of the Globe component
                          const placeholder = document.createElement('div');
                          placeholder.style.marginRight = '0.5rem';
                          placeholder.style.display = 'inline-flex';
                          placeholder.style.alignItems = 'center';
                          placeholder.style.justifyContent = 'center';
                          placeholder.style.width = '16px';
                          placeholder.style.height = '16px';
                          // Insert it before the img
                          parent.insertBefore(placeholder, imgElement);
                          // Render the Globe icon to this element (this can only be approximated using native methods)
                          placeholder.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>';
                        }
                      }}
                    />
                  )}
                  <span>{site.displayName}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      );
    }
  },
  
  // model_output type processor - model output
  {
    canHandle: (message) => message.type === "model_output",
    render: (message, _t) => (
      <div style={{
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        fontSize: "0.875rem",
        lineHeight: 1.5,
        color: message.subType === "deep_thinking" ? "#6b7280" : "#1f2937",
        fontWeight: 400
      }}>
        <MarkdownRenderer content={message.content} className="task-message-content" />
      </div>
    )
  },
  
  // execution type processor - execution result (not displayed)
  {
    canHandle: (message) => message.type === "execution",
    render: (_message, _t) => null // Return null, do not render this type of message
  },
  
  // error type processor - error information
  {
    canHandle: (message) => message.type === "error",
    render: (message, _t) => (
      <div style={{
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        fontSize: "0.875rem",
        lineHeight: 1.5,
        color: "#dc2626",
        fontWeight: 500,
        borderRadius: "0.25rem",
        paddingTop: "0.5rem"
      }}>
        <span>{message.content}</span>
      </div>
    )
  },
  
  // virtual type processor - virtual message (do not display content, only as a card container)
  {
    canHandle: (message) => message.type === "virtual",
    render: (_message, _t) => null
  },

  // default processor - should be placed at the end
  {
    canHandle: () => true,
    render: (message, t) => {
      const content = message.content;
      if (typeof content === 'string') {
        return <MarkdownRenderer content={content} className="task-message-content" />;
      } else {
        return (
          <pre style={{
            whiteSpace: "pre-wrap", 
            fontSize: "0.75rem",
            fontFamily: "monospace"
          }}>
            {JSON.stringify(content, null, 2)}
          </pre>
        );
      }
    }
  }
];

interface TaskWindowProps {
  messages: TaskMessageType[]
  isStreaming?: boolean
}

export function TaskWindow({
  messages,
  isStreaming = false
}: TaskWindowProps) {
  const { t } = useTranslation('common');
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [isExpanded, setIsExpanded] = useState(true) // default expand task details interface
  const [contentHeight, setContentHeight] = useState(0)
  const contentRef = useRef<HTMLDivElement>(null)
  
  // Add new refs for dynamic threshold calculation
  const prevContentHeightRef = useRef(0)
  const lastScrollTimeRef = useRef(Date.now())
  
  const { hasMessages, hasVisibleMessages, groupedMessages } = useChatTaskMessage(messages as ChatMessageType[]);

  // The function of scrolling to the bottom - defined early to avoid hoisting issues
  const scrollToBottom = () => {
    const scrollAreaElement = scrollAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]');
    if (!scrollAreaElement) return;
    
    // Use requestAnimationFrame to optimize performance
    requestAnimationFrame(() => {
      (scrollAreaElement as HTMLElement).scrollTop = (scrollAreaElement as HTMLElement).scrollHeight;
    });
  };

  // calculate the content height
  useEffect(() => {
    if (isExpanded && contentRef.current) {
      const height = contentRef.current.scrollHeight
      setContentHeight(height)
    }
  }, [isExpanded, groupedMessages, messages])

  // Dynamic threshold calculation based on content growth
  const calculateDynamicThreshold = (baseThreshold: number) => {
    const contentGrowth = contentHeight - prevContentHeightRef.current;
    const currentTime = Date.now();
    const timeDiff = currentTime - lastScrollTimeRef.current;
    
    // If content grew significantly (more than 200px) in a short time (less than 1 second)
    if (contentGrowth > 200 && timeDiff < 1000) {
      // Increase threshold proportionally to content growth, but cap it at reasonable limits
      const dynamicThreshold = Math.min(baseThreshold + contentGrowth * 0.8, 400);
      return dynamicThreshold;
    }
    
    // If content grew moderately (50-200px)
    if (contentGrowth > 50) {
      const dynamicThreshold = Math.min(baseThreshold + contentGrowth * 0.5, 250);
      return dynamicThreshold;
    }
    
    return baseThreshold;
  };

  // Listen for message changes and automatically scroll to the bottom (only when user allows it)
  useEffect(() => {
    if (isExpanded && autoScroll) {
      const scrollAreaElement = scrollAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]');
      if (!scrollAreaElement) return;

      const { scrollTop, scrollHeight, clientHeight } = scrollAreaElement as HTMLElement;
      const distanceToBottom = scrollHeight - scrollTop - clientHeight;
      
      // Use dynamic threshold for auto-scroll
      const dynamicThreshold = calculateDynamicThreshold(150);
      
      // Only auto-scroll if user is near the bottom (within dynamic threshold)
      if (distanceToBottom < dynamicThreshold) {
        // Use requestAnimationFrame to avoid too frequent updates
        requestAnimationFrame(() => {
          scrollToBottom();
        });
      }
      
      // Update tracking refs after scroll decision
      prevContentHeightRef.current = contentHeight;
      lastScrollTimeRef.current = Date.now();
    }
  }, [messages.length, isExpanded, autoScroll, contentHeight]);

  // Auto-scroll during streaming when user allows it
  useEffect(() => {
    if (autoScroll && isStreaming && isExpanded) {
      const scrollAreaElement = scrollAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]');
      if (!scrollAreaElement) return;

      const { scrollTop, scrollHeight, clientHeight } = scrollAreaElement as HTMLElement;
      const distanceToBottom = scrollHeight - scrollTop - clientHeight;
      
      // Use dynamic threshold for streaming auto-scroll (more sensitive base threshold)
      const dynamicThreshold = calculateDynamicThreshold(50);
      
      // Only auto-scroll during streaming if user is near the bottom (within dynamic threshold)
      if (distanceToBottom < dynamicThreshold) {
        scrollToBottom();
      }
      
      // Update tracking refs after scroll decision
      prevContentHeightRef.current = contentHeight;
      lastScrollTimeRef.current = Date.now();
    }
  }, [messages, autoScroll, isStreaming, isExpanded, contentHeight]);

  // Handle the scrolling event of the scroll area
  useEffect(() => {
    const scrollAreaElement = scrollAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]');
    
    if (!scrollAreaElement) return;
    
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = scrollAreaElement as HTMLElement;
      const distanceToBottom = scrollHeight - scrollTop - clientHeight;
      
      // If the distance to the bottom is less than 50px, it is considered that the user has scrolled to the bottom, and enable automatic scrolling
      if (distanceToBottom < 50) {
        setAutoScroll(true);
      } else if (distanceToBottom > 80) { 
        // If the distance to the bottom is greater than 80px, and it is user-initiated scrolling, disable automatic scrolling
        setAutoScroll(false);
      }
    };
    
    scrollAreaElement.addEventListener('scroll', handleScroll);
    
    return () => {
      scrollAreaElement.removeEventListener('scroll', handleScroll);
    };
  }, []);

  // The logic of automatically folding when the message changes
  useEffect(() => {
    if (!isStreaming && messages.length > 0) {
      const lastMessage = messages[messages.length - 1];
      // Check if the last message contains finalAnswer
      if (lastMessage.finalAnswer) {
        const timer = setTimeout(() => {
          setIsExpanded(false);
        }, 1000); // 1秒后折叠
        return () => clearTimeout(timer);
      }
    }
  }, [messages, isStreaming]);

  // Use the processor to render the message content
  const renderMessageContent = (message: any) => {
    // Find the first processor that can handle this message type
    
    const handler = messageHandlers.find(h => h.canHandle(message));
    if (handler) {
      return handler.render(message, t);
    }
    
    // Fallback processing, normally not executed here
    console.warn("No processor found:", { 
      messageType: message.type 
    });
    return <div className="text-sm text-gray-500">{t('taskWindow.unknownMessageType', { type: message.type })}</div>;
  };

  // Check if it is the last message
  const isLastMessage = (index: number, messages: any[]) => {
    return index === messages.length - 1;
  };

  // Check if a message should display a blinking dot
  const shouldBlinkDot = (message: any, index: number, messages: any[]) => {
    // As long as it is the last message and is streaming, it should blink, regardless of the message type
    return isStreaming && isLastMessage(index, messages);
  };

  // Render the message list
  const renderMessages = () => {
    if (!hasMessages) {
      return (
        <div className="text-center text-sm text-gray-400 mt-8">
          {t('taskWindow.noTaskMessages')}
        </div>
      );
    }

    if (!hasVisibleMessages) {
      return (
        <div className="text-center text-sm text-gray-400 mt-8">
          {t('taskWindow.noTaskMessages')}
        </div>
      );
    }

    return (
      <div className="relative">
        <div className="absolute left-[0.2rem] top-[1.25rem] bottom-0 w-0.5 bg-gray-200"></div>

        {groupedMessages.map((group, groupIndex) => {
          const message = group.message;
          const isBlinking = shouldBlinkDot(message, groupIndex, groupedMessages.map(g => g.message));
          
          return (
            <div key={message.id || groupIndex} className="relative mb-5">
              {/* 使用flex布局确保圆点与文本内容对齐 */}
              <div className="flex items-start">
                {/* 圆点容器 */}
                <div className="flex-shrink-0 mr-3" style={{ position: "relative", top: "0.95rem" }}>
                  <div 
                    className={isBlinking ? "blinkingDot" : ""}
                    style={isBlinking ? {
                      width: "0.5rem",
                      height: "0.5rem",
                      borderRadius: "9999px"
                    } : {
                      width: "0.5rem",
                      height: "0.5rem",
                      borderRadius: "9999px",
                      backgroundColor: message.type === "virtual" ? "transparent" : "#9ca3af"
                    }}
                  ></div>
                </div>
                
                {/* 消息内容 */}
                <div className="flex-1 text-sm break-words min-w-0">
                  {renderMessageContent(message)}
                  
                  {/* Render card messages */}
                  {group.cards.length > 0 && (
                    <div className="mt-2">
                      {group.cards.map((card, cardIndex) => (
                        <div key={`card-${cardIndex}`} className="ml-0">
                          {renderMessageContent(card)}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  // 计算容器高度：内容高度 + header高度，但不超过最大高度
  const maxHeight = 300
  const headerHeight = 55
  const availableHeight = maxHeight - headerHeight
  const actualContentHeight = Math.min(contentHeight + 16, availableHeight)
  const containerHeight = isExpanded ? headerHeight + actualContentHeight : 'auto'
  const needsScroll = contentHeight + 16 > availableHeight

  return (
    <>
      <div 
        className="relative rounded-lg mb-4 overflow-hidden border border-gray-200 bg-gray-50"
        style={{ 
          height: containerHeight,
          minHeight: isExpanded ? `${headerHeight}px` : 'auto'
        }}
      >
        <div className="px-1 py-2">
          <div className="flex items-center">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0 hover:bg-gray-100 rounded-full mr-2"
              onClick={() => setIsExpanded(!isExpanded)}
            >
              <ChevronRight className={`h-4 w-4 ${isExpanded ? 'rotate-90' : '-rotate-90'}`} />
            </Button>
            <span className="text-xs font-medium text-gray-500">{t('taskWindow.taskDetails')}</span>
          </div>
          {isExpanded && <div className="h-px bg-gray-200 mt-2" />}
        </div>
        
        {isExpanded && (
          <div className="px-4" style={{ height: `${actualContentHeight}px` }}>
            {needsScroll ? (
              <ScrollArea className="h-full" ref={scrollAreaRef}>
                <div className="" ref={contentRef}>
                  {renderMessages()}
                </div>
              </ScrollArea>
            ) : (
              <div className="" ref={contentRef}>
                {renderMessages()}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Add necessary CSS animations */}
      <style jsx global>{`
        @keyframes blinkingDot {
          0% { background-color: rgba(59, 130, 246, 0.5); }
          50% { background-color: rgba(79, 70, 229, 1); }
          100% { background-color: rgba(59, 130, 246, 0.5); }
        }
        .blinkingDot {
          animation: blinkingDot 1.5s infinite ease-in-out;
          background-color: rgba(79, 70, 229, 1);
          box-shadow: 0 0 5px rgba(79, 70, 229, 0.5);
        }
        
        /* For the code block style in task-message-content */
        .task-message-content pre {
          white-space: pre-wrap !important;
          word-wrap: break-word !important;
          word-break: break-word !important;
          overflow-wrap: break-word !important;
          overflow: auto !important;
          max-width: 100% !important;
          box-sizing: border-box !important;
          padding: 6px 10px !important;
          margin: 2px 0 !important;
        }
        
        .task-message-content code {
          white-space: pre-wrap !important;
          word-wrap: break-word !important;
          word-break: break-word !important;
          overflow-wrap: break-word !important;
          max-width: 100% !important;
          padding: 0 !important;
        }
        
        .task-message-content div[class*="language-"] {
          white-space: pre-wrap !important;
          word-wrap: break-word !important;
          word-break: break-word !important;
          overflow-wrap: break-word !important;
          overflow: auto !important;
          max-width: 100% !important;
          box-sizing: border-box !important;
          padding: 6px 10px !important;
          margin: 2px 0 !important;
        }
        
        /* Ensure the content of the SyntaxHighlighter component wraps correctly */
        .task-message-content .react-syntax-highlighter-line-number {
          white-space: nowrap !important;
        }
        
        /* Make sure the entire container is not stretched by the content */
        .task-message-content {
          overflow: hidden !important;
          max-width: 100% !important;
          word-wrap: break-word !important;
          word-break: break-word !important;
        }
        
        .task-message-content * {
          max-width: 100% !important;
          box-sizing: border-box !important;
        }
        
        /* Paragraph spacing adjustment */
        .task-message-content p {
          margin-bottom: 0.5rem !important;
          margin-top: 0.25rem !important;
        }
        
        .task-message-content .markdown-body p {
          margin-bottom: 0.5rem !important;
          margin-top: 0.25rem !important;
        }
      `}</style>
    </>
  )
} 