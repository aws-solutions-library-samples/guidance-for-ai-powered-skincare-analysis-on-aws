import { useState, FormEvent } from 'react';
import { motion } from 'motion/react';
import { LogIn, Mail, Lock, AlertCircle } from 'lucide-react';
import { Button } from '../components/ui/button';
import { AuthError, safeAuthError, signIn } from '../utils/auth';
import type { NewPasswordChallenge } from '../utils/auth';

interface SignInPageProps {
    onSuccess: () => void;
    onBack: () => void;
}

export const SignInPage = ({ onSuccess, onBack }: SignInPageProps) => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState<AuthError | null>(null);
    const [loading, setLoading] = useState(false);
    const [challenge, setChallenge] = useState<NewPasswordChallenge | null>(null);
    const [newPassword, setNewPassword] = useState('');
    const [confirmation, setConfirmation] = useState('');

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setError(null);
        setLoading(true);

        try {
            if (challenge) {
                if (newPassword !== confirmation) throw new AuthError('AUTH_PASSWORD_MISMATCH');
                await challenge.complete(newPassword);
                setNewPassword('');
                setConfirmation('');
                setChallenge(null);
            } else {
                const result = await signIn(email, password);
                setPassword('');
                if (result.status === 'new_password_required') {
                    setChallenge(result);
                    return;
                }
            }
            onSuccess();
        } catch (err) {
            setError(safeAuthError(err));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex flex-col items-center justify-center min-h-[85vh] px-4 sm:px-6">
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className="w-full max-w-md"
            >
                <div className="bg-white/70 backdrop-blur-xl rounded-2xl sm:rounded-3xl shadow-xl shadow-rose-100/50 border border-white/60 p-5 sm:p-8">
                    <div className="flex flex-col items-center mb-6 sm:mb-8">
                        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-rose-400 to-orange-400 flex items-center justify-center mb-4 shadow-lg shadow-rose-200">
                            <LogIn size={24} className="text-white" />
                        </div>
                        <h2 className="text-2xl font-serif font-bold text-gray-900">{challenge ? 'Choose Your Password' : 'Welcome Back'}</h2>
                        <p className="text-gray-500 text-sm mt-1">{challenge ? 'Replace your temporary password with a new password only you know.' : 'Sign in to start your skin analysis'}</p>
                    </div>

                    <form onSubmit={handleSubmit} className="space-y-4">
                        {!challenge && <div>
                            <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                            <div className="relative">
                                <Mail size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                                <input
                                    id="email"
                                    type="email"
                                    required
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    className="w-full pl-10 pr-4 py-3 rounded-xl border border-gray-200 bg-white/80 focus:outline-none focus:ring-2 focus:ring-rose-300 focus:border-transparent transition-all text-gray-900 placeholder-gray-400"
                                    placeholder="you@example.com"
                                    autoComplete="email"
                                />
                            </div>
                        </div>}

                        {!challenge && <div>
                            <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                            <div className="relative">
                                <Lock size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                                <input
                                    id="password"
                                    type="password"
                                    required
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="w-full pl-10 pr-4 py-3 rounded-xl border border-gray-200 bg-white/80 focus:outline-none focus:ring-2 focus:ring-rose-300 focus:border-transparent transition-all text-gray-900 placeholder-gray-400"
                                    placeholder="••••••••"
                                    autoComplete="current-password"
                                />
                            </div>
                        </div>}

                        {challenge && <>
                            <div>
                                <label htmlFor="new-password" className="block text-sm font-medium text-gray-700 mb-1">New password</label>
                                <input id="new-password" type="password" required autoComplete="new-password"
                                    value={newPassword} onChange={e => setNewPassword(e.target.value)}
                                    className="w-full px-4 py-3 rounded-xl border border-gray-200 bg-white/80 text-gray-900" />
                            </div>
                            <div>
                                <label htmlFor="confirm-password" className="block text-sm font-medium text-gray-700 mb-1">Confirm new password</label>
                                <input id="confirm-password" type="password" required autoComplete="new-password"
                                    value={confirmation} onChange={e => setConfirmation(e.target.value)}
                                    className="w-full px-4 py-3 rounded-xl border border-gray-200 bg-white/80 text-gray-900" />
                            </div>
                        </>}

                        {error && (
                            <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 rounded-xl px-4 py-3" role="alert">
                                <AlertCircle size={16} />
                                <div><p>{error.message}</p><p className="mt-1 text-xs font-mono">{error.code}</p></div>
                            </div>
                        )}

                        <Button type="submit" size="lg" className="w-full" disabled={loading}>
                            {loading ? 'Signing in...' : challenge ? 'Set Password and Sign In' : 'Sign In'}
                        </Button>
                    </form>

                    <button
                        onClick={onBack}
                        disabled={loading}
                        className="w-full mt-4 text-sm text-gray-500 hover:text-gray-700 transition-colors text-center"
                    >
                        ← Back to home
                    </button>
                </div>
            </motion.div>
        </div>
    );
};
