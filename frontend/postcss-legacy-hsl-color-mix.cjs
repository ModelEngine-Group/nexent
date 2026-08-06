const postcss = require("postcss");

const hslColorMixPattern =
  /^color-mix\(\s*in srgb\s*,\s*hsl\(\s*var\((--[\w-]+)\)\s*\)\s+([\d.]+)%\s*,\s*transparent\s*\)$/;
const legacyBrowserCondition = "not (color: color-mix(in srgb, red, blue))";

module.exports = {
  postcssPlugin: "legacy-hsl-color-mix-fallback",
  OnceExit(root) {
    root.walkRules((rule) => {
      const fallbackRule = postcss.rule({ selector: rule.selector });

      rule.each((node) => {
        if (node.type !== "decl") return;

        const match = node.value.match(hslColorMixPattern);

        if (!match) return;

        fallbackRule.append(
          postcss.decl({
            prop: node.prop,
            value: `hsl(var(${match[1]}) / ${match[2]}%)`,
            important: node.important,
          })
        );
      });

      if (fallbackRule.nodes.length === 0) return;

      const supportsRule = postcss.atRule({
        name: "supports",
        params: legacyBrowserCondition,
      });
      supportsRule.append(fallbackRule);
      rule.parent.insertBefore(rule, supportsRule);
    });
  },
};
