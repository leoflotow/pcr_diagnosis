<script setup lang="ts">
import { labels } from './api'
defineProps<{data:any,fields:string[],numbers?:string[],options?:Record<string,string[]>,required?:boolean,readonly?:boolean}>()
</script>
<template><div class="fields"><label v-for="key in fields" :key="key">{{labels[key]??key}}
  <select :disabled="readonly" v-if="options?.[key]" v-model="data[key]"><option v-for="option in options[key]" :key="option">{{option}}</option></select>
  <input :disabled="readonly" v-else-if="key==='performed_at'||key==='due_at'" type="datetime-local" v-model="data[key]" :required="required">
  <input :disabled="readonly" v-else-if="numbers?.includes(key)" type="number" min="0" step="any" :value="data[key]??''" @input="data[key]=($event.target as HTMLInputElement).value===''?null:Number(($event.target as HTMLInputElement).value)" placeholder="未知请留空">
  <textarea :disabled="readonly" v-else-if="['instructions','transfer_prompt','knowledge_note','protocol_notes','source','reason','note','verification_feedback','answer','reasoning','controls','hypothesis','variable','expected_result','interpretation','changed','kept','sample_result','expected_comparison'].includes(key)" v-model="data[key]" :required="required" rows="3" maxlength="5000"></textarea>
  <input :disabled="readonly" v-else v-model="data[key]" :required="required" maxlength="120">
</label></div></template>
