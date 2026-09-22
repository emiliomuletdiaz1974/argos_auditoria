// ARG-080 · the golden rule, enforced: gold shines only where something is accredited.
//
// Components know no colours: they use the tokens of `src/styles/tokens.css`, the only file that
// declares a raw colour. The gold (`--gold`) is allowed only in `src/styles/accredited.css`, the
// styles of the verdict and the credential. Anywhere else, the build fails.
const GOLD = ["/var\\(\\s*--gold/", "/#c9a227/i"];

export default {
  rules: {
    "color-no-hex": true,
    "color-named": "never",
    "function-disallowed-list": ["rgb", "rgba", "hsl", "hsla"],
    "declaration-property-value-disallowed-list": { "/.*/": GOLD },
  },
  overrides: [
    {
      files: ["src/styles/tokens.css"],
      rules: {
        "color-no-hex": null,
        "function-disallowed-list": null,
        "declaration-property-value-disallowed-list": null,
      },
    },
    {
      files: ["src/styles/accredited.css"],
      rules: { "declaration-property-value-disallowed-list": null },
    },
  ],
};
