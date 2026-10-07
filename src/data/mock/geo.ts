/** MOCK BACKEND — approximate municipality centroids (public geography). */
export interface Municipality {
  name: string;
  county: string;
  lat: number;
  lon: number;
}

export const MUNICIPALITIES: Municipality[] = [
  { name: 'Oslo', county: 'Oslo', lat: 59.913, lon: 10.752 },
  { name: 'Bergen', county: 'Vestland', lat: 60.391, lon: 5.322 },
  { name: 'Trondheim', county: 'Trøndelag', lat: 63.43, lon: 10.395 },
  { name: 'Stavanger', county: 'Rogaland', lat: 58.97, lon: 5.733 },
  { name: 'Bodø', county: 'Nordland', lat: 67.28, lon: 14.405 },
  { name: 'Tromsø', county: 'Troms', lat: 69.649, lon: 18.956 },
  { name: 'Ålesund', county: 'Møre og Romsdal', lat: 62.472, lon: 6.149 },
  { name: 'Kristiansand', county: 'Agder', lat: 58.146, lon: 7.996 },
  { name: 'Drammen', county: 'Buskerud', lat: 59.744, lon: 10.204 },
  { name: 'Fredrikstad', county: 'Østfold', lat: 59.22, lon: 10.934 },
  { name: 'Bærum', county: 'Akershus', lat: 59.894, lon: 10.524 },
  { name: 'Asker', county: 'Akershus', lat: 59.833, lon: 10.435 },
  { name: 'Lillehammer', county: 'Innlandet', lat: 61.115, lon: 10.466 },
  { name: 'Haugesund', county: 'Rogaland', lat: 59.413, lon: 5.268 },
  { name: 'Molde', county: 'Møre og Romsdal', lat: 62.737, lon: 7.16 },
  { name: 'Hamar', county: 'Innlandet', lat: 60.795, lon: 11.068 },
  { name: 'Narvik', county: 'Nordland', lat: 68.438, lon: 17.427 },
  { name: 'Sandnes', county: 'Rogaland', lat: 58.852, lon: 5.735 },
  { name: 'Tønsberg', county: 'Vestfold', lat: 59.267, lon: 10.407 },
  { name: 'Kongsberg', county: 'Buskerud', lat: 59.668, lon: 9.65 },
  { name: 'Arendal', county: 'Agder', lat: 58.461, lon: 8.772 },
  { name: 'Alta', county: 'Finnmark', lat: 69.968, lon: 23.272 },
  { name: 'Mo i Rana', county: 'Nordland', lat: 66.313, lon: 14.142 },
  { name: 'Skien', county: 'Telemark', lat: 59.209, lon: 9.609 },
];

export const MUNI_BY_NAME: Record<string, Municipality> = Object.fromEntries(MUNICIPALITIES.map((m) => [m.name, m]));

/** World regions the backend resolves for globe focus (mock). */
export const REGIONS: Record<string, { lat: number; lon: number }> = {
  norway: { lat: 64.5, lon: 12 },
  sweden: { lat: 62, lon: 16 },
  denmark: { lat: 56, lon: 10 },
  europe: { lat: 52, lon: 10 },
  'united kingdom': { lat: 54, lon: -2 },
  germany: { lat: 51, lon: 10 },
  'united states': { lat: 39, lon: -98 },
};
