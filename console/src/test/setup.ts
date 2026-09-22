import "@testing-library/jest-dom/vitest";

// jsdom has no object URLs: a download in a test only needs them to exist.
if (!URL.createObjectURL) {
  URL.createObjectURL = () => "blob:test";
  URL.revokeObjectURL = () => undefined;
}
