user_library <- file.path(
  Sys.getenv("LOCALAPPDATA"),
  "R",
  "win-library",
  paste(R.version$major, strsplit(R.version$minor, "\\.")[[1]][1], sep = ".")
)

.libPaths(c(user_library, .libPaths()))
suppressPackageStartupMessages(library(bibliometrix))
suppressPackageStartupMessages(library(ggplot2))

input_file <- "screening_decisions_with_reasons.csv"
output_dir <- "bibliometrics"
dir.create(output_dir, showWarnings = FALSE)

records <- read.csv(
  input_file,
  fileEncoding = "UTF-8-BOM",
  stringsAsFactors = FALSE,
  check.names = FALSE,
  na.strings = c("", "NA")
)
thesaurus <- read.csv(
  "keyword_thesaurus.csv",
  fileEncoding = "UTF-8-BOM",
  stringsAsFactors = FALSE,
  check.names = FALSE
)

clean_value <- function(x) {
  x <- trimws(as.character(x))
  x[is.na(x)] <- ""
  x
}

save_citation_bar <- function(data) {
  data <- head(data, 12)
  data$title <- vapply(
    strwrap(data$title, width = 64, simplify = FALSE),
    paste,
    collapse = "\n",
    character(1)
  )
  data$title <- factor(data$title, levels = rev(data$title))
  figure <- ggplot(data, aes(x = title, y = citations)) +
    geom_col(fill = "#356A8A", width = 0.72) +
    coord_flip() +
    labs(
      title = "Most cited records currently marked relevant",
      x = NULL,
      y = "Maximum citations reported by Scopus or WoS"
    ) +
    theme_minimal(base_size = 10) +
    theme(
      plot.title = element_text(face = "bold"),
      panel.grid.minor = element_blank()
    )
  ggsave(file.path(output_dir, "citations.png"), figure,
         width = 9.5, height = 8.2, dpi = 220)
  ggsave(file.path(output_dir, "citations.pdf"), figure,
         width = 9.5, height = 8.2)
}

normalize_keyword <- function(x) {
  x <- tolower(clean_value(x))
  x <- gsub("[_-]+", " ", x)
  x <- gsub("[[:punct:]]+", " ", x)
  x <- gsub("\\s+", " ", trimws(x))
  mapping <- setNames(
    tolower(thesaurus$canonical),
    tolower(thesaurus$variant)
  )
  mapped <- unname(mapping[x])
  x[!is.na(mapped)] <- mapped[!is.na(mapped)]
  x[nchar(x) > 1]
}

normalize_source <- function(x) {
  x <- trimws(clean_value(x))
  key <- tolower(x)
  x <- tools::toTitleCase(key)
  x[key == "elife"] <- "eLife"
  x[key == "plos one"] <- "PLOS ONE"
  x
}

split_field <- function(values, separator = ";") {
  lapply(clean_value(values), function(value) {
    if (!nzchar(value)) return(character())
    unique(trimws(strsplit(value, separator, fixed = TRUE)[[1]]))
  })
}

frequency_table <- function(values, normalize = identity) {
  items <- unlist(lapply(split_field(values), normalize), use.names = FALSE)
  items <- items[nzchar(items)]
  result <- sort(table(items), decreasing = TRUE)
  data.frame(
    item = names(result),
    records = as.integer(result),
    row.names = NULL,
    check.names = FALSE
  )
}

save_bar <- function(data, label, title, filename, top_n = 12) {
  data <- head(data, top_n)
  data$item <- factor(data$item, levels = rev(data$item))
  figure <- ggplot(data, aes(x = item, y = records)) +
    geom_col(fill = "#356A8A", width = 0.72) +
    coord_flip() +
    labs(title = title, x = NULL, y = label) +
    theme_minimal(base_size = 11) +
    theme(
      plot.title = element_text(face = "bold"),
      panel.grid.minor = element_blank()
    )
  ggsave(file.path(output_dir, paste0(filename, ".png")), figure,
         width = 8.2, height = 5.2, dpi = 220)
  ggsave(file.path(output_dir, paste0(filename, ".pdf")), figure,
         width = 8.2, height = 5.2)
}

records$decision <- toupper(clean_value(records$decision))
records$year_num <- suppressWarnings(as.integer(records$year))
records$citation_scopus <- suppressWarnings(as.numeric(records$scopus_cited_by))
records$citation_wos <- suppressWarnings(as.numeric(records$wos_times_cited))
records$citations <- pmax(
  records$citation_scopus,
  records$citation_wos,
  na.rm = TRUE
)
records$citations[is.infinite(records$citations)] <- NA_real_
records$keywords_normalized <- vapply(
  split_field(records$keywords),
  function(items) paste(unique(normalize_keyword(items)), collapse = ";"),
  character(1)
)

corpus <- data.frame(
  AU = clean_value(records$authors),
  AF = clean_value(records$authors),
  TI = clean_value(records$title),
  SO = normalize_source(records$journal),
  SR = paste(normalize_source(records$journal), clean_value(records$record_id), sep = "_"),
  PY = records$year_num,
  DT = clean_value(records$doc_type),
  DE = records$keywords_normalized,
  C1 = clean_value(records$affiliations),
  TC = records$citations,
  DI = clean_value(records$doi),
  AB = clean_value(records$abstract),
  DB = "Scopus/WoS merged",
  stringsAsFactors = FALSE
)
corpus <- corpus[!is.na(corpus$PY) & nzchar(corpus$TI), ]
selected <- records[records$decision == "INCLUDE", ]

analysis <- biblioAnalysis(corpus, sep = ";")
summary_output <- capture.output(
  print(summary(analysis, k = 20, pause = FALSE))
)
writeLines(summary_output, file.path(output_dir, "summary.txt"), useBytes = TRUE)

selected_corpus <- corpus[records$decision == "INCLUDE", ]
selected_corpus$SO <- ifelse(
  tolower(selected_corpus$SO) == "elife",
  "eLife",
  tools::toTitleCase(tolower(selected_corpus$SO))
)
network <- biblioNetwork(
  selected_corpus,
  analysis = "co-occurrences",
  network = "author_keywords",
  sep = ";"
)

annual <- as.data.frame(table(corpus$PY), stringsAsFactors = FALSE)
names(annual) <- c("year", "papers")
annual$year <- as.integer(as.character(annual$year))
included_annual <- as.data.frame(table(selected$year_num), stringsAsFactors = FALSE)
names(included_annual) <- c("year", "included")
included_annual$year <- as.integer(as.character(included_annual$year))
annual <- merge(annual, included_annual, by = "year", all.x = TRUE)
annual$included[is.na(annual$included)] <- 0L
write.csv(annual, file.path(output_dir, "annual_production.csv"), row.names = FALSE)

scale_factor <- max(annual$papers) / max(annual$included)
annual_figure <- ggplot(annual, aes(x = year)) +
  geom_col(aes(y = papers), fill = "#B8C6CC", width = 0.72) +
  geom_line(aes(y = included * scale_factor), color = "#C05A3A", linewidth = 0.9) +
  geom_point(aes(y = included * scale_factor), color = "#C05A3A", size = 1.8) +
  labs(
    title = "Publication output and currently relevant records",
    subtitle = "2026 is partial; line shows ASReview INCLUDE labels (right axis)",
    x = "Publication year",
    y = "Full-corpus records"
  ) +
  scale_x_continuous(breaks = seq(min(annual$year), max(annual$year), 2)) +
  scale_y_continuous(
    sec.axis = sec_axis(~ . / scale_factor, name = "Currently relevant records")
  ) +
  theme_minimal(base_size = 11) +
  theme(plot.title = element_text(face = "bold"))
ggsave(file.path(output_dir, "annual_production.png"), annual_figure,
       width = 8.2, height = 4.8, dpi = 220)
ggsave(file.path(output_dir, "annual_production.pdf"), annual_figure,
       width = 8.2, height = 4.8)

authors <- frequency_table(selected$authors)
write.csv(authors, file.path(output_dir, "authors.csv"), row.names = FALSE)
save_bar(
  authors,
  "Currently relevant records",
  "Authors most represented in the current relevant set",
  "authors",
  12
)

institutions <- frequency_table(selected$affiliations)
write.csv(institutions, file.path(output_dir, "institutions.csv"), row.names = FALSE)
save_bar(
  institutions,
  "Currently relevant records reporting affiliation",
  "Institutions most represented in the current relevant set",
  "institutions",
  12
)

keywords <- frequency_table(selected$keywords, normalize_keyword)
write.csv(keywords, file.path(output_dir, "keywords.csv"), row.names = FALSE)
save_bar(
  keywords,
  "Currently relevant records",
  "Normalized keyword fields in the current relevant set",
  "keywords",
  15
)

sources <- frequency_table(selected$journal, normalize_source)
write.csv(sources, file.path(output_dir, "sources.csv"), row.names = FALSE)
elife_count <- sum(selected$journal |> normalize_source() == "eLife")
source_groups <- data.frame(
  item = c("eLife", paste0("Other venues (", nrow(sources) - 1, " titles)")),
  records = c(elife_count, nrow(selected) - elife_count)
)
write.csv(
  source_groups,
  file.path(output_dir, "source_groups.csv"),
  row.names = FALSE
)
save_bar(
  source_groups,
  "Currently relevant records",
  "Publication outlets in the relevant set",
  "sources",
  2
)

cited <- selected[
  !is.na(selected$citations),
  c("year", "title", "doi", "citation_scopus", "citation_wos", "citations")
]
cited <- cited[order(-cited$citations), ]
write.csv(cited, file.path(output_dir, "included_citations.csv"), row.names = FALSE)
save_citation_bar(cited)

coverage <- data.frame(
  group = c("Full corpus", "Currently relevant"),
  records = c(nrow(records), nrow(selected)),
  abstracts = c(sum(nzchar(clean_value(records$abstract))),
                sum(nzchar(clean_value(selected$abstract)))),
  author_lists = c(sum(nzchar(clean_value(records$authors))),
                   sum(nzchar(clean_value(selected$authors)))),
  affiliations = c(sum(nzchar(clean_value(records$affiliations))),
                   sum(nzchar(clean_value(selected$affiliations)))),
  indexed_keywords = c(sum(nzchar(clean_value(records$keywords))),
                       sum(nzchar(clean_value(selected$keywords)))),
  citation_counts = c(sum(!is.na(records$citations)),
                      sum(!is.na(selected$citations)))
)
write.csv(coverage, file.path(output_dir, "metadata_coverage.csv"), row.names = FALSE)

if (sum(network) > 0) {
  png(file.path(output_dir, "keyword_network.png"),
      width = 1800, height = 1400, res = 220)
  networkPlot(
    network,
    normalize = "association",
    n = 18,
    type = "fruchterman",
    size = TRUE,
    labelsize = 0.6,
    remove.isolates = TRUE,
    cluster = "louvain",
    Title = "Keyword co-occurrence in the currently relevant set"
  )
  dev.off()
}

collaboration <- biblioNetwork(
  selected_corpus,
  analysis = "collaboration",
  network = "authors",
  sep = ";"
)
if (sum(collaboration) > 0) {
  png(file.path(output_dir, "coauthorship_network.png"),
      width = 1800, height = 1400, res = 220)
  networkPlot(
    collaboration,
    normalize = "association",
    n = 18,
    type = "fruchterman",
    size = TRUE,
    labelsize = 0.6,
    remove.isolates = TRUE,
    cluster = "louvain",
    Title = "Co-authorship in the currently relevant set"
  )
  dev.off()
}

write.csv(
  data.frame(
    measure = c(
      "Full deduplicated corpus",
      "Currently relevant records",
      "Excluded records",
      "Unclear records",
      "Citation indicator"
    ),
    value = c(
      nrow(records),
      sum(records$decision == "INCLUDE"),
      sum(records$decision == "EXCLUDE"),
      sum(records$decision == "UNCLEAR"),
      "Per-record maximum of Scopus and WoS citation counts; not additive"
    )
  ),
  file.path(output_dir, "review_scope.csv"),
  row.names = FALSE
)

cat("bibliometrix:", as.character(packageVersion("bibliometrix")), "\n")
cat("Records:", nrow(records), " | Currently relevant:", nrow(selected), "\n")
cat("Results written to", normalizePath(output_dir), "\n")
