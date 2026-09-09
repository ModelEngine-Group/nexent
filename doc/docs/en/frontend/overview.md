# Frontend Architecture Overview

Nexent's frontend is built with modern React technologies, providing a responsive and intuitive user interface for AI agent interactions.

## Technology Stack

- **Framework**: Next.js 15 (App Router)
- **Language**: TypeScript
- **UI Library**: React 18 + Ant Design 6 + Assistant UI + Tailwind CSS
- **State Management**: React Hooks + zustand + TanStack Query
- **Internationalization**: react-i18next
- **HTTP Client**: Fetch API (server-side requests forwarded via Node.js http-proxy)

## Directory Structure

```
frontend/
├── app/                          # Next.js App Router
│   └── [locale]/                 # Internationalization routes (zh/en)
│       ├── newchat/              # Chat interface (assistant-ui)
│       ├── chat/                 # Chat interface (legacy)
│       │   ├── components/       # Chat interface components
│       │   ├── internal/         # Chat core logic
│       │   └── streaming/        # Streaming response handling
│       ├── agents/               # Agent configuration and debugging
│       ├── agent-repository/     # Agent repository (publish/review)
│       ├── agent-space/          # Agent space
│       ├── agent-tasks/          # Agent automation tasks
│       ├── aidp-knowledges/      # AIDP knowledge bases
│       ├── evaluation/           # Agent evaluation
│       ├── knowledges/           # Knowledge base management
│       ├── models/               # Model configuration
│       ├── memory/               # Memory management
│       ├── market/               # Agent marketplace
│       ├── mcp-space/            # MCP tool space
│       ├── skill-space/          # Skill space
│       ├── oauth/                # OAuth callback page
│       ├── owner-manage/         # Platform owner management
│       ├── resource-manage/      # Resource management
│       ├── share/                # Share pages
│       ├── space/                # Space
│       ├── users/                # User center
│       ├── layout.tsx            # Global layout
│       └── layout.client.tsx     # Client layout
├── components/                    # Reusable UI components
│   ├── agent/                    # Agent-related components
│   ├── auth/                     # Authentication components
│   ├── navigation/               # Navigation components
│   ├── permission/               # Permission control components
│   ├── providers/                # Context providers
│   ├── settings/                 # Settings components
│   └── ui/                       # Basic UI component library
├── const/                        # Constant definitions (error codes, page configuration, etc.)
├── contexts/                     # React Context definitions
├── ext_components/               # External integration components (AIDP, etc.)
├── features/                     # Business feature modules (agent automation, etc.)
├── services/                     # API service layer
│   ├── api.ts                    # Basic API configuration (endpoints and request wrapper)
│   ├── authService.ts            # Authentication service
│   ├── conversationService.ts    # Conversation service
│   ├── agentConfigService.ts     # Agent configuration service
│   ├── knowledgeBaseService.ts   # Knowledge base service
│   ├── modelService.ts           # Model service
│   ├── mcpService.ts             # MCP tool service
│   ├── skillService.ts           # Skill service
│   └── uploadService.ts          # File upload service (among 30+ services)
├── hooks/                        # Custom React Hooks
├── stores/                       # zustand global state
├── lib/                          # Utility libraries
├── types/                        # TypeScript type definitions
├── styles/                       # Global styles (CSS)
├── tests/                        # Unit tests
├── utils/                        # Utility functions
├── public/                       # Static resources
│   └── locales/                  # Internationalization files (zh/en)
└── middleware.ts                 # Next.js middleware
```

## Architecture Responsibilities

### **Presentation Layer**
- User interface and interaction logic
- Component-based architecture for reusability
- Responsive design for multiple devices

### **Service Layer**
- Encapsulates API calls and data transformation
- Handles communication with backend services
- Manages error handling and retry logic

### **State Management**
- React Hooks for component state management
- Context providers for global state
- Real-time updates for streaming responses

### **Internationalization**
- Support for English and Chinese languages
- Dynamic language switching
- Localized content and UI elements

### **Routing Management**
- Based on Next.js App Router
- Locale-aware routing
- Dynamic route generation

## Key Features

### Real-time Chat Interface
- Streaming response handling
- Message history management
- Multi-modal input support (text, voice, images)

### Configuration Management
- Model provider configuration
- Agent behavior customization
- Knowledge base management

### Responsive Design
- Mobile-first approach
- Adaptive layouts
- Touch-friendly interactions

### Performance Optimization
- Server-side rendering (SSR)
- Static site generation (SSG)
- Code splitting and lazy loading
- Image optimization

## Development Workflow

### Setup
```bash
cd frontend
npm install
npm run dev
```

### Building for Production
```bash
npm run build
npm start
```

- Supports base URL building (at runtime, `base-path.mjs` reads `NEXT_PUBLIC_BASE_PATH` to adapt BASE_PATH), so the app can be deployed under a reverse proxy subpath
- App logo and description are customizable (configured in the admin console)
- Production port is unified as 3000

### Code Quality
- ESLint for code linting (`npm run lint`)
- Prettier for code formatting (`npm run format`)
- TypeScript for type safety (`npm run type-check`)
- One-shot check: `npm run check-all` (type-check + lint + format:check + build)

## Integration Points

### Backend Communication
- RESTful API calls
- WebSocket for real-time features
- Authentication and authorization
- Error handling and user feedback

### External Services
- Model provider APIs
- File upload and management
- Voice processing integration
- Analytics and monitoring

For detailed development guidelines and component documentation, see the [Developer Guide](../developer-guide/overview).