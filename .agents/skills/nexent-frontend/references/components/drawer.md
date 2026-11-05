# Drawers

Use the pinned ui Sheet parts for new drawer compositions. The only migrated production drawer shell currently belongs to file preview, so it lives in `components/preview/PreviewDrawerShell`. The shell preserves width, localized close controls, retained drafts via Activity and outside-dismissal policy. Preview owns requests and content. StandardDrawer and the one-consumer common Sheet wrapper have been removed; do not create a general drawer abstraction before actual reuse exists.
