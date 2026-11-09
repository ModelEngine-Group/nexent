# Runtime investigation

The original v2.8.4 research established that replacing the class alone did not preserve native assistant/tool histories: smolagents textual memory conversion required a separately owned loop. smolagents remains at the repository version; an upgrade alone did not resolve that boundary. That experiment remains available on feature/v284-native-toolcalling, with historical findings and evidence there.

Develop now supplies ResolvedModelProfile, ModelService, registered native/code converters, parameter rules and model/provider catalog selection. The new feature uses these capabilities instead of migrating the old OpenAIModel private-client adapter. Global runtime selection is a request; effective runtime is resolved per model. Reasoning support does not select the tool loop.

Live migration testing found empty tool-call ID continuation fragments at the configured gateway. The stream decoder now accepts those omissions without relaxing complete call identities. Live testing also exposed an outdated acceptance filter for span name native.generate; model-service spans use the selected display name and carry model.request_purpose=native_agent. Tests check that explicit marker and the actual protocol exchange.

Both branches previously accepted text without retaining finish_reason. Their completion policy now validates a complete generation before authorizing effects. Public native text previously flowed through the legacy thinking parser; it now has a separate observer/projection path. The unrelated math-rendering fix #4256 is already present on develop and is not backported into the v2.8.4 branch by this change.
