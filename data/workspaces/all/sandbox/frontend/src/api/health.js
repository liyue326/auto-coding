import axios from 'axios';

const baseURL = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

export const getHealth = () => {
  return axios.get(`${baseURL}/api/health`);
};
