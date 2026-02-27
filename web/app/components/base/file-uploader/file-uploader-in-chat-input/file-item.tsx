import type { FileEntity } from '../types'
import {
  RiCloseLine,
  RiDownloadLine,
} from '@remixicon/react'
import { useState } from 'react'
import ActionButton from '@/app/components/base/action-button'
import Button from '@/app/components/base/button'
import AudioPreview from '@/app/components/base/file-uploader/audio-preview'
import PdfPreview from '@/app/components/base/file-uploader/dynamic-pdf-preview'
import VideoPreview from '@/app/components/base/file-uploader/video-preview'
import { ReplayLine } from '@/app/components/base/icons/src/vender/other'
import ProgressCircle from '@/app/components/base/progress-bar/progress-circle'
import { cn } from '@/utils/classnames'
import { downloadUrl } from '@/utils/download'
import { formatFileSize } from '@/utils/format'
import FileTypeIcon from '../file-type-icon'
import {
  fileIsUploaded,
  getFileAppearanceType,
  getFileExtension,
} from '../utils'

type FileItemProps = {
  file: FileEntity
  showDeleteAction?: boolean
  showDownloadAction?: boolean
  canPreview?: boolean
  onRemove?: (fileId: string) => void
  onReUpload?: (fileId: string) => void
}
const FileItem = ({
  file,
  showDeleteAction,
  showDownloadAction = true,
  onRemove,
  onReUpload,
  canPreview,
}: FileItemProps) => {
  const { id, name, type, progress, url, base64Url, isRemote } = file
  const [previewUrl, setPreviewUrl] = useState('')
  const ext = getFileExtension(name, type, isRemote)
  const uploadError = progress === -1

  let tmp_preview_url = url || base64Url
  if (!tmp_preview_url && file?.originalFile)
    tmp_preview_url = URL.createObjectURL(file.originalFile.slice()).toString()
  const download_url = url ? `${url}&as_attachment=true` : base64Url

  const isPdf = type?.split('/')[1] === 'pdf' || ext?.toLowerCase() === 'pdf'
  const isUploaded = fileIsUploaded(file)

  return (
    <>
      <div
        className={cn(
          'group/file-item relative w-[220px] rounded-xl border border-components-panel-border bg-components-card-bg shadow-sm transition-all duration-150',
          !uploadError && 'hover:border-components-panel-border-bold hover:shadow-md hover:bg-components-card-bg-alt',
          uploadError && 'border-state-destructive-border bg-state-destructive-hover',
        )}
      >
        {
          showDeleteAction && (
            <Button
              className="absolute -right-1.5 -top-1.5 z-[11] hidden h-5 w-5 rounded-full p-0 group-hover/file-item:flex"
              onClick={() => onRemove?.(id)}
            >
              <RiCloseLine className="h-4 w-4 text-components-button-secondary-text" />
            </Button>
          )
        }
        <div
          className={cn('flex items-center gap-2.5 px-3 py-2.5', canPreview && 'cursor-pointer')}
          onClick={() => canPreview && setPreviewUrl(tmp_preview_url || '')}
        >
          {/* File type icon — larger for PDF */}
          <div className={cn(
            'flex shrink-0 items-center justify-center rounded-lg',
            isPdf ? 'h-9 w-9 bg-[#FEE2E2]' : 'h-8 w-8 bg-components-card-bg-alt',
          )}>
            <FileTypeIcon
              size={isPdf ? 'lg' : 'md'}
              type={getFileAppearanceType(name, type)}
            />
          </div>

          {/* Name + meta */}
          <div className="min-w-0 flex-1">
            <div
              className="truncate text-[13px] font-medium leading-tight text-text-primary"
              title={name}
            >
              {name}
            </div>
            <div className="mt-0.5 flex items-center gap-1 text-[11px] text-text-tertiary">
              {ext && (
                <span className={cn(
                  'rounded px-1 py-0.5 font-semibold uppercase leading-none tracking-wide',
                  isPdf ? 'bg-[#FEE2E2] text-[#DC2626]' : 'bg-components-card-bg-alt text-text-tertiary',
                )}>
                  {ext}
                </span>
              )}
              {!!file.size && (
                <span className="text-text-tertiary">{formatFileSize(file.size)}</span>
              )}
            </div>
          </div>

          {/* Download / progress / retry — always visible when uploaded */}
          <div className="ml-auto shrink-0">
            {showDownloadAction && download_url && isUploaded && (
              <ActionButton
                size="m"
                className="flex"
                onClick={(e) => {
                  e.stopPropagation()
                  downloadUrl({ url: download_url || '', fileName: name, target: '_blank' })
                }}
              >
                <RiDownloadLine className="h-4 w-4 text-text-secondary" />
              </ActionButton>
            )}
            {progress >= 0 && !isUploaded && (
              <ProgressCircle percentage={progress} size={14} className="shrink-0" />
            )}
            {uploadError && (
              <ReplayLine
                className="h-4 w-4 text-state-destructive-text"
                onClick={() => onReUpload?.(id)}
              />
            )}
          </div>
        </div>
      </div>
      {
        type?.split('/')[0] === 'audio' && canPreview && previewUrl && (
          <AudioPreview
            title={name}
            url={previewUrl}
            onCancel={() => setPreviewUrl('')}
          />
        )
      }
      {
        type?.split('/')[0] === 'video' && canPreview && previewUrl && (
          <VideoPreview
            title={name}
            url={previewUrl}
            onCancel={() => setPreviewUrl('')}
          />
        )
      }
      {
        type?.split('/')[1] === 'pdf' && canPreview && previewUrl && (
          <PdfPreview url={previewUrl} onCancel={() => { setPreviewUrl('') }} />
        )
      }
    </>
  )
}

export default FileItem
