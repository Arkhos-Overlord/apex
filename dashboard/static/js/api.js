/* APEX Dashboard — API client helper */

const BASE = ""; // relative to serving host

async function api(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Accept": "application/json", ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new APIError(res.status, body.detail || "Request failed", path);
  }
  return res.json();
}

class APIError extends Error {
  constructor(status, message, path) {
    super(message);
    this.status = status;
    this.path = path;
  }
}

/* Convenience wrappers */
const apiClient = {
  learnerProgress: (id) => api(`/api/learner/${id}/progress`),
  learnerHeatmap: (id, courseId) => api(`/api/learner/${id}/heatmap?course_id=${encodeURIComponent(courseId)}`),
  learnerKnowledgeGraph: (id, courseId) => api(`/api/learner/${id}/knowledge-graph?course_id=${encodeURIComponent(courseId)}`),
  learnerSchedule: (id, courseId) => api(`/api/learner/${id}/schedule?course_id=${encodeURIComponent(courseId)}`),
  listCourses: () => api("/api/courses"),
  courseProgress: (courseId) => api(`/api/course/${courseId}/progress`),
};
