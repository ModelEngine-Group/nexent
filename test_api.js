// 在浏览器控制台执行这段代码来直接测试 API
(async () => {
  try {
    console.log("Testing GET /api/indices?include_stats=true...");
    const response = await fetch("/api/indices?include_stats=true", {
      headers: {
        "Authorization": "Bearer " + (localStorage.getItem("token") || "")
      }
    });
    console.log("Response status:", response.status);
    const data = await response.json();
    console.log("Response data:", data);
  } catch (error) {
    console.error("API Error:", error);
  }
})();
