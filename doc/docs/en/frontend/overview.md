# Frontend Architecture Overview

Nexent's frontend is built with modern React technologies, providing a responsive and intuitive user interface for AI agent interactions.

## Technology Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **UI Library**: React + Tailwind CSS
- **State Management**: React Hooks
- **Internationalization**: react-i18next
- **HTTP Client**: Fetch API

## Directory Structure

```
frontend/
├── app/                          # Next.js App Router
│   └── [locale]/                 # Internationalization routes (zh/en)
│       ├── chat/                 # Chat interface
│       │   ├── internal/         # Chat core logic
│       │   ├── layout/           # Chat interface layout components
│       │   └── streaming/        # Streaming response handling
│       ├── setup/                # System settings pages
│       │   ├── agentSetup/       # Agent configuration
│       │   ├── knowledgeBaseSetup/ # Knowledge base configuration
│       │   └── modelSetup/       # Model configuration
│       └── layout.tsx            # Global layout
├── components/                    # Reusable UI components
│   ├── providers/                # Context providers
│   └── ui/                       # Basic UI component library
├── services/                     # API service layer
│   ├── api.ts                    # Basic API configuration
│   ├── conversationService.ts    # Conversation service
│   ├── agentConfigService.ts     # Agent configuration service
│   ├── knowledgeBaseService.ts   # Knowledge base service
│   └── modelService.ts           # Model service
├── hooks/                        # Custom React Hooks
├── lib/                          # Utility libraries
├── types/                        # TypeScript type definitions
├── public/                       # Static resources
│   └── locales/                  # Internationalization files
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

### Code Quality
- ESLint for code linting
- Prettier for code formatting
- TypeScript for type safety
- Husky for pre-commit hooks

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