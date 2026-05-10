/* Wrappers API pour les endpoints classrooms */
window.TeacherAPI = (function () {
  const BASE = '/api/v1';

  async function _req(method, path, body) {
    const opts = {
      method,
      credentials: 'include',
      headers: body ? { 'Content-Type': 'application/json' } : {},
    };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(BASE + path, opts);
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    if (r.status === 204) return null;
    return r.json();
  }

  async function _upload(path, formData) {
    const r = await fetch(BASE + path, { method: 'POST', credentials: 'include', body: formData });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return r.json();
  }

  return {
    // Classrooms
    listClassrooms: () => _req('GET', '/classrooms'),
    createClassroom: (data) => _req('POST', '/classrooms', data),
    updateClassroom: (id, data) => _req('PUT', `/classrooms/${id}`, data),
    archiveClassroom: (id) => _req('DELETE', `/classrooms/${id}`),

    // Students
    listStudents: (cid) => _req('GET', `/classrooms/${cid}/students`),
    enrollStudents: (cid, userIds) => _req('POST', `/classrooms/${cid}/students`, { user_ids: userIds }),
    unenrollStudent: (cid, uid) => _req('DELETE', `/classrooms/${cid}/students/${uid}`),
    importStudentsCSV: (cid, file) => {
      const fd = new FormData();
      fd.append('file', file);
      return _upload(`/classrooms/${cid}/students/import`, fd);
    },

    // Assignments
    listAssignments: (cid) => _req('GET', `/classrooms/${cid}/assignments`),
    createAssignment: (cid, data) => _req('POST', `/classrooms/${cid}/assignments`, data),
    updateAssignment: (cid, aid, data) => _req('PUT', `/classrooms/${cid}/assignments/${aid}`, data),
    archiveAssignment: (cid, aid) => _req('DELETE', `/classrooms/${cid}/assignments/${aid}`),
    deployAssignment: (cid, aid) => _req('POST', `/classrooms/${cid}/assignments/${aid}/deploy-all`),

    // Templates (pour le select)
    listTemplates: () => _req('GET', '/k8s/templates'),

    // Teacher dashboard
    dashboard: () => _req('GET', '/teacher/dashboard'),

    // User search (pour l'inscription manuelle)
    searchUsers: (q) => _req('GET', `/teacher/users/search?q=${encodeURIComponent(q)}`),
  };
})();
