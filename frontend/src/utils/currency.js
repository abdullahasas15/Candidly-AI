// Currency formatting helper for Candidly AI

export const getCurrencySymbol = (currency = 'USD') => {
  if (!currency) return '$';
  switch (currency.toUpperCase()) {
    case 'INR':
      return '₹';
    case 'EUR':
      return '€';
    case 'GBP':
      return '£';
    case 'CAD':
      return 'C$';
    case 'AUD':
      return 'A$';
    case 'SGD':
      return 'S$';
    case 'JPY':
      return '¥';
    case 'USD':
    default:
      return '$';
  }
};

export const formatMoney = (val, currency = 'USD') => {
  if (val === null || val === undefined || isNaN(val) || val === '') {
    return 'Not Stated';
  }
  const symbol = getCurrencySymbol(currency);
  return `${symbol}${Number(val).toLocaleString()} ${currency || 'USD'}`;
};

export const formatSalaryRange = (min, max, currency = 'USD') => {
  if (!min && !max) return 'Competitive compensation';
  const symbol = getCurrencySymbol(currency);
  if (min && max) {
    return `${symbol}${Number(min).toLocaleString()} - ${symbol}${Number(max).toLocaleString()} ${currency || 'USD'}`;
  }
  if (min) {
    return `From ${symbol}${Number(min).toLocaleString()} ${currency || 'USD'}`;
  }
  return `Up to ${symbol}${Number(max).toLocaleString()} ${currency || 'USD'}`;
};
