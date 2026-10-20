import { describe, expect, it } from "vitest";
import { enResources, zhCNResources } from "./resources";

function flatten(value: unknown, prefix = ""): Record<string, string> {
  if (typeof value === "string") return { [prefix]: value };
  if (typeof value !== "object" || value === null) {
    throw new TypeError(`Invalid translation at ${prefix}`);
  }
  return Object.entries(value).reduce<Record<string, string>>(
    (result, [key, child]) => Object.assign(result, flatten(child, prefix ? `${prefix}.${key}` : key)),
    {},
  );
}

function interpolationVariables(value: string): string[] {
  return [...value.matchAll(/{{\s*([^,}\s]+)[^}]*}}/g)].map((match) => match[1]).sort();
}

const zhCN = flatten(zhCNResources);
const en = flatten(enResources);

describe("translation resources", () => {
  it("keeps identical key hierarchies in both languages", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(zhCN).sort());
  });

  it("contains no empty translations", () => {
    for (const value of [...Object.values(zhCN), ...Object.values(en)]) {
      expect(value.trim()).not.toBe("");
    }
  });

  it("keeps interpolation variables consistent", () => {
    for (const key of Object.keys(zhCN)) {
      expect(interpolationVariables(en[key]), key).toEqual(interpolationVariables(zhCN[key]));
    }
  });
});
