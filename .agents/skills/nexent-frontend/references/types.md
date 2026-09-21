# Types and runtime values

- Export shared types; organize files by existing domain conventions.
- Use interfaces for object shapes, props, and API contracts; type aliases for unions, primitives, and computed types.
- Define separate request/response types, explicit optional fields, and status unions. Use generics/utility/mapped/conditional types for concrete needs.
- Document complex types with concise English JSDoc. Keep required/optional props clear.
- `frontend/types/` holds no runtime values. Put runtime enums, literals, config, and status constants in `frontend/const/`. Executable guards belong in `frontend/lib/` or an appropriate runtime module.
- Do not log in type-definition modules; runtime consumers use `frontend/lib/logger.ts`.
- Verify consumers with the project's TypeScript check after contract changes.
