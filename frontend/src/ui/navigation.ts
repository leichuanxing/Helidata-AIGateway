import {ref} from 'vue'

// Reflect router work rather than using a timer that can finish before the page loads.
export const navigating=ref(false)
