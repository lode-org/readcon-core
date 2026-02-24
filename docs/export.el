;; Batch export org-mode files to RST for Sphinx
;; Usage: emacs --batch -l docs/export.el

(require 'ox-rst)

(defun readcon--export-org-to-rst ()
  "Export all .org files in docs/orgmode/ to .rst in docs/source/."
  (let ((org-dir (expand-file-name "docs/orgmode/" default-directory))
        (rst-dir (expand-file-name "docs/source/" default-directory)))
    (dolist (org-file (directory-files org-dir t "\\.org$"))
      (let* ((base (file-name-sans-extension (file-name-nondirectory org-file)))
             (rst-file (expand-file-name (concat base ".rst") rst-dir)))
        (with-current-buffer (find-file-noselect org-file)
          (let ((org-export-with-toc nil)
                (org-export-with-section-numbers nil))
            (org-rst-export-as-rst)
            (write-file rst-file)
            (kill-buffer)))
        (message "Exported %s -> %s" org-file rst-file)))))

(readcon--export-org-to-rst)
