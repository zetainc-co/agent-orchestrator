import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { io, Socket } from 'socket.io-client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConversationStatus = 'open' | 'pending' | 'resolved' | 'snoozed'
type MessageType = 0 | 1 | 2 | 3 // incoming | outgoing | activity | template

interface ChatwootMessage {
  id: number
  content: string | null
  message_type: MessageType
  content_type: string
  private: boolean
  created_at: number
  conversation_id: number
  sender: { id: number; name: string; type: string; avatar_url: string } | null
  attachments: unknown[]
}

interface ChatwootConversation {
  id: number
  inbox_id: number
  status: ConversationStatus
  timestamp: number
  unread_count: number
  labels: string[]
  meta: {
    sender: { id: number; name: string; phone_number: string; thumbnail: string }
    assignee: unknown | null
  }
  messages?: ChatwootMessage[]
  last_non_activity_message?: ChatwootMessage | null
}

// Shapes that `queryClient.getQueryData` returns before the `select` transform
interface ConversationsListResponse {
  data: {
    meta: unknown
    payload: ChatwootConversation[]
  }
}

interface MessagesResponse {
  payload: ChatwootMessage[]
}

// Socket event payloads emitted by NestJS ChatwootWebhookService
interface MessageCreatedPayload extends ChatwootMessage {}

interface ConversationStatusChangedPayload {
  conversationId: number
  status: ConversationStatus
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseConversationsSocketOptions {
  tenantId: string | undefined
  socketUrl: string
}

export function useConversationsSocket({
  tenantId,
  socketUrl,
}: UseConversationsSocketOptions): void {
  const queryClient = useQueryClient()
  const socketRef = useRef<Socket | null>(null)

  useEffect(() => {
    if (!tenantId) return

    // Connect (or reuse existing connection)
    const socket: Socket = io(socketUrl, {
      transports: ['websocket'],
      reconnectionAttempts: 5,
      reconnectionDelay: 2000,
    })
    socketRef.current = socket

    socket.on('connect', () => {
      console.info('[socket] connected:', socket.id)
      socket.emit('join-tenant', { tenantId })
    })

    socket.on('disconnect', (reason) => {
      console.info('[socket] disconnected:', reason)
    })

    // ------------------------------------------------------------------
    // message:created
    // Append message to messages cache + update matching conversation
    // ------------------------------------------------------------------
    socket.on('message:created', (message: MessageCreatedPayload) => {
      const { conversation_id } = message

      // 1. Append to messages cache
      queryClient.setQueryData<MessagesResponse>(
        ['messages', conversation_id],
        (prev) => {
          if (!prev) return prev
          const alreadyExists = prev.payload.some((m) => m.id === message.id)
          if (alreadyExists) return prev
          return { ...prev, payload: [...prev.payload, message] }
        }
      )

      // 2. Update last_non_activity_message + unread_count in all conversation caches
      if (message.message_type !== 2 /* not activity */) {
        queryClient.setQueriesData<ConversationsListResponse>(
          { queryKey: ['conversations'] },
          (prev) => {
            if (!prev) return prev
            return {
              ...prev,
              data: {
                ...prev.data,
                payload: prev.data.payload.map((conv) => {
                  if (conv.id !== conversation_id) return conv
                  return {
                    ...conv,
                    last_non_activity_message: message,
                    unread_count:
                      message.message_type === 0 // incoming
                        ? conv.unread_count + 1
                        : conv.unread_count,
                  }
                }),
              },
            }
          }
        )
      }
    })

    // ------------------------------------------------------------------
    // conversation:updated
    // Replace the matching conversation in all caches
    // ------------------------------------------------------------------
    socket.on('conversation:updated', (conversation: ChatwootConversation) => {
      queryClient.setQueriesData<ConversationsListResponse>(
        { queryKey: ['conversations'] },
        (prev) => {
          if (!prev) return prev
          const exists = prev.data.payload.some((c) => c.id === conversation.id)
          if (!exists) return prev
          return {
            ...prev,
            data: {
              ...prev.data,
              payload: prev.data.payload.map((c) =>
                c.id === conversation.id ? conversation : c
              ),
            },
          }
        }
      )
    })

    // ------------------------------------------------------------------
    // conversation:created
    // Prepend to all conversation caches
    // ------------------------------------------------------------------
    socket.on('conversation:created', (conversation: ChatwootConversation) => {
      queryClient.setQueriesData<ConversationsListResponse>(
        { queryKey: ['conversations'] },
        (prev) => {
          if (!prev) return prev
          const alreadyExists = prev.data.payload.some(
            (c) => c.id === conversation.id
          )
          if (alreadyExists) return prev
          return {
            ...prev,
            data: {
              ...prev.data,
              payload: [conversation, ...prev.data.payload],
            },
          }
        }
      )
    })

    // ------------------------------------------------------------------
    // conversation:status-changed
    // Update only the status field of the matching conversation
    // ------------------------------------------------------------------
    socket.on(
      'conversation:status-changed',
      ({ conversationId, status }: ConversationStatusChangedPayload) => {
        queryClient.setQueriesData<ConversationsListResponse>(
          { queryKey: ['conversations'] },
          (prev) => {
            if (!prev) return prev
            return {
              ...prev,
              data: {
                ...prev.data,
                payload: prev.data.payload.map((c) =>
                  c.id === conversationId ? { ...c, status } : c
                ),
              },
            }
          }
        )
      }
    )

    return () => {
      socket.removeAllListeners()
      socket.disconnect()
      socketRef.current = null
    }
  }, [tenantId, socketUrl, queryClient])
}
