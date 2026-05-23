<script setup>
import { ref, onMounted } from 'vue';
import notesApi from '../api/notes';

const notes = ref([]);
const newNote = ref({ title: '', content: '' });
const editingNote = ref(null);
const isEditing = ref(false);
const loading = ref(false);
const error = ref('');

// 获取所有笔记
const fetchNotes = async () => {
  try {
    const response = await notesApi.getNotes();
    notes.value = response.data;
  } catch (err) {
    error.value = '无法获取笔记列表';
    console.error(err);
  }
};

// 创建新笔记
const createNote = async () => {
  if (!newNote.value.title || !newNote.value.content) {
    error.value = '标题和内容不能为空';
    return;
  }

  try {
    loading.value = true;
    await notesApi.createNote(newNote.value);
    newNote.value = { title: '', content: '' };
    await fetchNotes();
  } catch (err) {
    error.value = '创建笔记失败';
    console.error(err);
  } finally {
    loading.value = false;
  }
};

// 开始编辑笔记
const startEdit = (note) => {
  editingNote.value = note;
  isEditing.value = true;
};

// 更新笔记
const updateNote = async () => {
  if (!editingNote.value.title || !editingNote.value.content) {
    error.value = '标题和内容不能为空';
    return;
  }

  try {
    loading.value = true;
    await notesApi.updateNote(editingNote.value.id, editingNote.value);
    isEditing.value = false;
    await fetchNotes();
  } catch (err) {
    error.value = '更新笔记失败';
    console.error(err);
  } finally {
    loading.value = false;
  }
};

// 删除笔记
const deleteNote = async (id) => {
  try {
    await notesApi.deleteNote(id);
    await fetchNotes();
  } catch (err) {
    error.value = '删除笔记失败';
    console.error(err);
  }
};

// 初始化
onMounted(() => {
  fetchNotes();
});
</script>

<template>
  <div class="container mx-auto p-4">
    <h1 class="text-2xl font-bold mb-4">我的笔记</h1>

    <div v-if="error" class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative mb-4" role="alert">
      {{ error }}
    </div>

    <div class="mb-4">
      <h2 class="text-xl font-semibold mb-2">{{ isEditing ? '编辑笔记' : '新建笔记' }}</h2>
      <form @submit.prevent="isEditing ? updateNote() : createNote()">
        <div class="mb-2">
          <label for="title" class="block text-sm font-medium text-gray-700">标题</label>
          <input 
            type="text"
            id="title"
            v-model="isEditing ? editingNote.title : newNote.title"
            class="mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
            required
          />
        </div>
        <div class="mb-4">
          <label for="content" class="block text-sm font-medium text-gray-700">内容</label>
          <textarea
            id="content"
            v-model="isEditing ? editingNote.content : newNote.content"
            rows="4"
            class="mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
            required
          ></textarea>
        </div>
        <button
          type="submit"
          :disabled="loading"
          class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
        >
          {{ isEditing ? '更新笔记' : '创建笔记' }}
        </button>
      </form>
    </div>

    <div class="overflow-x-auto">
      <table class="min-w-full divide-y divide-gray-200">
        <thead class="bg-gray-50">
          <tr>
            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">标题</th>
            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">内容</th>
            <th scope="col" class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">操作</th>
          </tr>
        </thead>
        <tbody class="bg-white divide-y divide-gray-200">
          <tr v-for="(note, index) in notes" :key="note.id">
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{{ note.title }}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ note.content }}</td>
            <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
              <button
                @click="startEdit(note)"
                class="text-indigo-600 hover:text-indigo-900 mr-3"
              >编辑</button>
              <button
                @click="deleteNote(note.id)"
                class="text-red-600 hover:text-red-900"
              >删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
