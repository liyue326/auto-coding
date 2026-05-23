import axios from 'axios';

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  }
});

export default {
  getNotes() {
    return apiClient.get('/api/notes');
  },
  createNote(data) {
    return apiClient.post('/api/notes', data);
  },
  updateNote(id, data) {
    return apiClient.put(`/api/notes/${id}`, data);
  },
  deleteNote(id) {
    return apiClient.delete(`/api/notes/${id}`);
  }
};
