# Collaborative Agent Version Label Design

## Goal

Show the user-provided version name next to each related internal agent in the
agent configuration page.

## Scope

- Add an optional version-name field to the collaborative agent list item.
- Render `V{version_name}` next to the internal agent name in smaller, muted
  text.
- Pass the version name already resolved from the saved relation or the
  published agent into the internal list.
- Do not change external A2A agent rendering, the version publishing form, or
  backend APIs.

## Display Rule

The version name is rendered exactly as stored, preceded by a capital `V`.
The UI does not validate, normalize, or remove a user-provided `v`/`V` prefix.

## Verification

Run the frontend TypeScript check and Prettier validation for the modified
component.
