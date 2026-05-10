/* État partagé du dashboard enseignant */
window.TeacherState = (function () {
  let _classrooms = [];
  let _selectedClassroomId = null;
  let _templates = [];

  return {
    getClassrooms() { return _classrooms; },
    setClassrooms(list) { _classrooms = list; },
    getSelectedId() { return _selectedClassroomId; },
    setSelectedId(id) { _selectedClassroomId = id ? parseInt(id, 10) : null; },
    getSelectedClassroom() { return _classrooms.find(c => c.id === _selectedClassroomId) || null; },
    getTemplates() { return _templates; },
    setTemplates(list) { _templates = list; },
  };
})();
