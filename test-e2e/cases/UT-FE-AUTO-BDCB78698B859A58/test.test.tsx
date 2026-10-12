import { describe, expect, it } from "vitest";
import { API_BASE_URL, API_ENDPOINTS } from "@/services/api";

type ListingParams = Parameters<
  typeof API_ENDPOINTS.agentRepository.listings
>[0];

const tagPredicates = [{ key: "分类", value: "对话" }];
const searchTagPredicates = [{ key: "难度", value: "入门" }];
const tag = " 客服 ";

function splitQuery(url: string): {
  path: string;
  params: URLSearchParams;
} {
  const index = url.indexOf("?");
  if (index === -1) {
    return { path: url, params: new URLSearchParams() };
  }
  return {
    path: url.slice(0, index),
    params: new URLSearchParams(url.slice(index + 1)),
  };
}

describe(
  "Agent/Skill 仓库 tag_predicates/search_tag_predicates/tag 查询串序列化与 tagStats 端点解析",
  () => {
    it("UT-FE-AUTO-BDCB78698B859A58 agentRepository.listings 序列化 tag_predicates/search_tag_predicates 并去除 tag 首尾空格", () => {
      const url = API_ENDPOINTS.agentRepository.listings({
        tag_predicates: tagPredicates,
        search_tag_predicates: searchTagPredicates,
        tag,
      });
      const { path, params } = splitQuery(url);

      expect(path).toBe(`${API_BASE_URL}/repository/agent`);
      expect(params.get("tag_predicates")).toBe(JSON.stringify(tagPredicates));
      expect(params.get("search_tag_predicates")).toBe(
        JSON.stringify(searchTagPredicates)
      );
      expect(params.get("tag")).toBe("客服");
    });

    it("agentRepository.mineAgents 返回 /repository/agent/mine 并附加 tag_predicates 与 search_tag_predicates", () => {
      const url = API_ENDPOINTS.agentRepository.mineAgents({
        tag_predicates: tagPredicates,
        search_tag_predicates: searchTagPredicates,
      });
      const { path, params } = splitQuery(url);

      expect(path).toBe(`${API_BASE_URL}/repository/agent/mine`);
      expect(params.get("tag_predicates")).toBe(JSON.stringify(tagPredicates));
      expect(params.get("search_tag_predicates")).toBe(
        JSON.stringify(searchTagPredicates)
      );
    });

    it("skillRepository.listings 返回 /repository/skill 并附加 tag_predicates 与 tag", () => {
      const url = API_ENDPOINTS.skillRepository.listings({
        tag_predicates: tagPredicates,
        tag,
      });
      const { path, params } = splitQuery(url);

      expect(path).toBe(`${API_BASE_URL}/repository/skill`);
      expect(params.get("tag_predicates")).toBe(JSON.stringify(tagPredicates));
      expect(params.get("tag")).toBe("客服");
    });

    it("skillRepository.mineSkills 返回 /repository/skill/mine 并附加 tag_predicates", () => {
      const url = API_ENDPOINTS.skillRepository.mineSkills({
        tag_predicates: tagPredicates,
      });
      const { path, params } = splitQuery(url);

      expect(path).toBe(`${API_BASE_URL}/repository/skill/mine`);
      expect(params.get("tag_predicates")).toBe(JSON.stringify(tagPredicates));
    });

    it("agentRepository.tagStats 恒等于 /repository/agent/tags", () => {
      expect(API_ENDPOINTS.agentRepository.tagStats).toBe(
        `${API_BASE_URL}/repository/agent/tags`
      );
    });

    it("skillRepository.tagStats 恒等于 /repository/skill/tags", () => {
      expect(API_ENDPOINTS.skillRepository.tagStats).toBe(
        `${API_BASE_URL}/repository/skill/tags`
      );
    });

    it("空数组 tag_predicates/search_tag_predicates 不追加查询参数", () => {
      const url = API_ENDPOINTS.agentRepository.listings({
        tag_predicates: [],
        search_tag_predicates: [],
      });
      const { path, params } = splitQuery(url);

      expect(path).toBe(`${API_BASE_URL}/repository/agent`);
      expect(params.has("tag_predicates")).toBe(false);
      expect(params.has("search_tag_predicates")).toBe(false);
      expect(params.toString()).toBe("");
    });

    it("纯空白 tag 不追加 tag 参数", () => {
      const url = API_ENDPOINTS.agentRepository.listings({ tag: "   " });
      const { params } = splitQuery(url);

      expect(params.has("tag")).toBe(false);
      expect(params.toString()).toBe("");
    });

    it("undefined/null params 不产生查询串与多余 '?'", () => {
      const undefUrl = API_ENDPOINTS.agentRepository.listings(undefined);
      const nullUrl = API_ENDPOINTS.agentRepository.listings(
        null as unknown as ListingParams
      );

      expect(undefUrl).toBe(`${API_BASE_URL}/repository/agent`);
      expect(undefUrl).not.toContain("?");
      expect(nullUrl).toBe(`${API_BASE_URL}/repository/agent`);
      expect(nullUrl).not.toContain("?");
    });

    it("相同参数仅出现一次，无重复参数", () => {
      const url = API_ENDPOINTS.agentRepository.listings({
        tag_predicates: tagPredicates,
        search_tag_predicates: searchTagPredicates,
        tag,
      });
      const { params } = splitQuery(url);

      expect(params.getAll("tag_predicates")).toHaveLength(1);
      expect(params.getAll("search_tag_predicates")).toHaveLength(1);
      expect(params.getAll("tag")).toHaveLength(1);
    });
  }
);
