CREATE OR REPLACE FUNCTION public.match_clinics_simple (
  query_embedding_text TEXT,
  match_count int
)
RETURNS SETOF clinics_data
LANGUAGE plpgsql
AS $$
DECLARE
  query_embedding_vector vector(768);
BEGIN
  query_embedding_vector := query_embedding_text::vector;

  RETURN QUERY
  SELECT *
  FROM
    public.clinics_data
  ORDER BY
    clinics_data.embedding <=> query_embedding_vector
  LIMIT
    match_count;
END;
$$;