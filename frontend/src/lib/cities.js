// Major cities per country for the client form's City suggestions.
// Keyed by LOWERCASED country name — the same convention COUNTRY_DIAL_CODE
// uses — so lookups survive casing differences in stored data.
//
// This is a curated suggestion list, not a validation list: the City field
// stays free text (the backend stores CharField), so a city missing here can
// still be typed — extend a country's array as new markets appear, exactly
// like PHONE_COUNTRIES in constants.js.
const CITIES_BY_COUNTRY = {
  india: [
    "Agra", "Ahmedabad", "Alappuzha", "Amritsar", "Bengaluru", "Bhopal",
    "Bhubaneswar", "Chandigarh", "Chennai", "Coimbatore", "Dehradun",
    "Faridabad", "Ghaziabad", "Gurugram", "Guwahati", "Hyderabad", "Indore",
    "Jaipur", "Jodhpur", "Kannur", "Kanpur", "Kochi", "Kolkata", "Kollam",
    "Kottayam", "Kozhikode", "Lucknow", "Ludhiana", "Madurai", "Malappuram",
    "Mangaluru", "Mumbai", "Mysuru", "Nagpur", "Nashik", "New Delhi", "Noida",
    "Palakkad", "Panaji", "Patna", "Pune", "Raipur", "Rajkot", "Ranchi",
    "Salem", "Surat", "Thiruvananthapuram", "Thrissur", "Tiruchirappalli",
    "Udaipur", "Vadodara", "Varanasi", "Vijayawada", "Visakhapatnam",
  ],
  "united arab emirates": [
    "Abu Dhabi", "Ajman", "Al Ain", "Dubai", "Fujairah", "Ras Al Khaimah",
    "Sharjah", "Umm Al Quwain",
  ],
  "saudi arabia": [
    "Abha", "Buraidah", "Dammam", "Dhahran", "Hail", "Jeddah", "Jubail",
    "Khamis Mushait", "Khobar", "Mecca", "Medina", "Najran", "Riyadh",
    "Tabuk", "Taif", "Yanbu",
  ],
  qatar: [
    "Al Khor", "Al Rayyan", "Al Wakrah", "Doha", "Dukhan", "Lusail",
    "Mesaieed", "Umm Salal",
  ],
  oman: [
    "Barka", "Duqm", "Ibri", "Muscat", "Nizwa", "Rustaq", "Salalah", "Seeb",
    "Sohar", "Sur",
  ],
  kuwait: [
    "Ahmadi", "Fahaheel", "Farwaniya", "Hawally", "Jahra", "Kuwait City",
    "Mangaf", "Salmiya",
  ],
  bahrain: [
    "Budaiya", "Hamad Town", "Isa Town", "Manama", "Muharraq", "Riffa",
    "Sitra",
  ],
  // City-state: the only sensible value is the country itself.
  singapore: ["Singapore"],
  malaysia: [
    "Cyberjaya", "George Town", "Ipoh", "Johor Bahru", "Kota Kinabalu",
    "Kuala Lumpur", "Kuantan", "Kuching", "Malacca City", "Petaling Jaya",
    "Putrajaya", "Seremban", "Shah Alam", "Subang Jaya",
  ],
  "sri lanka": [
    "Anuradhapura", "Batticaloa", "Colombo", "Dehiwala-Mount Lavinia",
    "Galle", "Jaffna", "Kandy", "Kurunegala", "Matara", "Moratuwa",
    "Negombo", "Sri Jayawardenepura Kotte", "Trincomalee",
  ],
  bangladesh: [
    "Barisal", "Chittagong", "Comilla", "Cox's Bazar", "Dhaka", "Gazipur",
    "Khulna", "Mymensingh", "Narayanganj", "Rajshahi", "Rangpur", "Sylhet",
  ],
  nepal: [
    "Bhaktapur", "Biratnagar", "Birgunj", "Butwal", "Dharan", "Hetauda",
    "Itahari", "Janakpur", "Kathmandu", "Lalitpur", "Nepalgunj", "Pokhara",
  ],
  "united states": [
    "Atlanta", "Austin", "Boston", "Charlotte", "Chicago", "Columbus",
    "Dallas", "Denver", "Detroit", "Houston", "Indianapolis", "Jacksonville",
    "Las Vegas", "Los Angeles", "Memphis", "Miami", "Minneapolis",
    "Nashville", "New Orleans", "New York", "Orlando", "Philadelphia",
    "Phoenix", "Pittsburgh", "Portland", "Raleigh", "Salt Lake City",
    "San Antonio", "San Diego", "San Francisco", "San Jose", "Seattle",
    "Tampa", "Washington",
  ],
  canada: [
    "Brampton", "Calgary", "Edmonton", "Halifax", "Hamilton", "Kitchener",
    "London", "Mississauga", "Montreal", "Ottawa", "Quebec City", "Regina",
    "Saskatoon", "Surrey", "Toronto", "Vancouver", "Victoria", "Winnipeg",
  ],
  "united kingdom": [
    "Aberdeen", "Belfast", "Birmingham", "Brighton", "Bristol", "Cambridge",
    "Cardiff", "Coventry", "Edinburgh", "Glasgow", "Leeds", "Leicester",
    "Liverpool", "London", "Manchester", "Newcastle upon Tyne", "Nottingham",
    "Oxford", "Portsmouth", "Reading", "Sheffield", "Southampton",
  ],
  australia: [
    "Adelaide", "Brisbane", "Cairns", "Canberra", "Darwin", "Geelong",
    "Gold Coast", "Hobart", "Melbourne", "Newcastle", "Perth", "Sydney",
    "Townsville", "Wollongong",
  ],
  germany: [
    "Berlin", "Bonn", "Bremen", "Cologne", "Dortmund", "Dresden",
    "Düsseldorf", "Essen", "Frankfurt", "Hamburg", "Hanover", "Leipzig",
    "Mannheim", "Munich", "Nuremberg", "Stuttgart",
  ],
  france: [
    "Angers", "Bordeaux", "Dijon", "Grenoble", "Lille", "Lyon", "Marseille",
    "Montpellier", "Nantes", "Nice", "Paris", "Reims", "Rennes",
    "Strasbourg", "Toulon", "Toulouse",
  ],
  japan: [
    "Chiba", "Fukuoka", "Hiroshima", "Kawasaki", "Kitakyushu", "Kobe",
    "Kyoto", "Nagasaki", "Nagoya", "Naha", "Osaka", "Saitama", "Sapporo",
    "Sendai", "Tokyo", "Yokohama",
  ],
  china: [
    "Beijing", "Changsha", "Chengdu", "Chongqing", "Dalian", "Guangzhou",
    "Hangzhou", "Kunming", "Nanjing", "Ningbo", "Qingdao", "Shanghai",
    "Shenyang", "Shenzhen", "Suzhou", "Tianjin", "Wuhan", "Xi'an", "Xiamen",
    "Zhengzhou",
  ],
};

// Suggestions for a country name as stored on the form ("India"). Unknown or
// blank country → no suggestions (never the whole world's list).
export function getCitySuggestions(country) {
  return CITIES_BY_COUNTRY[(country ?? "").trim().toLowerCase()] ?? [];
}
