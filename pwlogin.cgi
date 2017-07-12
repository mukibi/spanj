#!/usr/bin/perl

use strict;
use warnings;

use Digest::SHA qw /sha1_hex/;
use Fcntl qw/:flock SEEK_END/;
use DBI;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my $str;

my @session_data;
my %session;

my $authd = 0;
my $xss_attempt = 0;
my $login = 0;
my $uid;
my $id;
my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
my $cont = "/";
my $key_unlock = 0;

if ( exists $ENV{"HTTP_SESSION"} ) {	
	@session_data = split/\&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {	
		@tuple = split/\=/,$unprocd_tuple;
		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	if (exists $session{"id"} and $session{"id"} =~ /^([0-9]+)$/) {
		$authd++;
		$id = $1;
	}
}

if (exists $ENV{"QUERY_STRING"} and $ENV{"QUERY_STRING"} =~ /&?cont=(.+)&?/i) {
	$cont = $1;
}

#not authenticated
#either the user has
#just posted auth
#data or they haven't

if (not $authd) {

	#process auth data

	if (exists $ENV{"REQUEST_METHOD"} and $ENV{"REQUEST_METHOD"} eq "POST") {	
		$login++;
		if (exists $session{"tries"}) {
			$session{"tries"} = $session{"tries"}+1;
		}
		else {
			$session{"tries"} = 1;	
		}
        	while (<STDIN>) {	
                	$str .= $_;
        	}
		my $spc = " "; 
		$str =~ s/\+/$spc/ge;
		my %auth_params;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}

		if ( exists $auth_params{"username"} and exists $auth_params{"password"} and exists $auth_params{"auth_token0"} ) {
			my $uname = $auth_params{"username"};
			my $pword = $auth_params{"password"};
			my $token = $auth_params{"auth_token0"};	
	
			if ($token eq $session{"auth_token0"}) {
	   	     my $con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
				if ($con) {
					my $prep_stmt = $con->prepare("SELECT u_id,u_name,salt,password FROM users WHERE u_name=?");
					if ($prep_stmt) {
						my $rc = $prep_stmt->execute($uname);
						if ($rc) {
							while (my @valid = $prep_stmt->fetchrow_array()) {
								my $pass_hash = uc( sha1_hex($pword . $valid[2]) );
								if ($pass_hash eq $valid[3]) {
									#decrypt key
									#for bursar and accounts clerk(s)
									my $success = 1;
									if ($valid[0] == 2 or ($valid[0] % 17) == 0) {

										$success = 0;
										$key_unlock++;

										my $salt = $valid[2];
										my $u_id = $valid[0];

										#try unlocking the keys
										#read the keys
										my $prep_stmt1 = $con->prepare("SELECT init_vec,aes_key,bit_riss FROM enc_keys WHERE u_id=? LIMIT 1");
										if ($prep_stmt1) {
											my $rc = $prep_stmt1->execute($valid[0]);
											if ($rc) {
												my ($xord_init_vec, $xord_aes_key,$bit_riss) = (undef, undef, undef);
												while ( my @valid = $prep_stmt1->fetchrow_array() ) {

													$xord_init_vec = $valid[0];
													$xord_aes_key = $valid[1];
													$bit_riss = $valid[2];

												}

												if ( defined $xord_init_vec ) {
													#use PBKDF2 to get the init_vec
													#and key
													use Crypt::PBKDF2;
													my $pbkdf2 = Crypt::PBKDF2->new(output_len => 32, salt_len => length($salt) + 1);

													my $pwd_key = $pbkdf2->PBKDF2($salt . "0", $pword);

													my @pwd_key_bytes = unpack("C*", $pwd_key);
													my @xord_key_bytes = unpack("C*", $xord_aes_key);

													my @key_bytes = ();

													for ( my $i = 0; $i < scalar(@xord_key_bytes); $i++ ) {
														$key_bytes[$i] = $xord_key_bytes[$i] ^ $pwd_key_bytes[$i];
													}

													my $pwd_iv = $pbkdf2->PBKDF2($salt . "1", $pword);

													my @pwd_iv_bytes_0 = unpack("C*", $pwd_iv);
													my @pwd_iv_bytes = splice(@pwd_iv_bytes_0, 0, 16);
													my @xord_iv_bytes = unpack("C*", $xord_init_vec);

													my @iv_bytes = ();
													for (my $i = 0; $i < scalar(@xord_iv_bytes); $i++) {
														$iv_bytes[$i] = $xord_iv_bytes[$i] ^ $pwd_iv_bytes[$i];
													}

													my $key = pack("C*", @key_bytes);
													my $iv = pack("C*", @iv_bytes);

													#try decrypt $bit_riss
													use Crypt::Rijndael;

													my $cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
 
													$cipher->set_iv($iv);
													my $packed = $cipher->decrypt($bit_riss);
													my @bytes = unpack("C*", $packed);
	
													my $final_index = $#bytes;
													my $pad_size = $bytes[$final_index];

													my $msg_valid = 1;
													#verify msg
	
													for ( my $i = 1; $i < $pad_size; $i++ ) {
														unless ( $bytes[$final_index - $i] == $pad_size ) {
															$msg_valid = 0;
															last;
														}
													}

													if ($msg_valid) {
														my $msg_size = ($final_index + 1) - $pad_size;
														my $msg = unpack("A${msg_size}", $packed);

														if ( $msg eq "bit_riss" ) {
															#generate random key to
															#encrypt the keys during this session
															use Crypt::Random::Source qw/get_strong/;

															my $sess_key = get_strong(48);
															my @sess_key_bytes = unpack("C*", $sess_key);

															my @iv_reencd_bytes = splice(@sess_key_bytes, 32);
															my @key_reencd_bytes = @sess_key_bytes;

															my (@reencd_iv, @reencd_key);

															for (my  $i = 0; $i < scalar(@iv_bytes); $i++ ) {
																$reencd_iv[$i] = $iv_bytes[$i] ^ $iv_reencd_bytes[$i];
															}

															for (my $j = 0; $j < scalar(@key_bytes); $j++ ) {
																$reencd_key[$j] = $key_bytes[$j] ^ $key_reencd_bytes[$j];
															}

															my $encrypted_iv = pack("C*", @reencd_iv);
															my $encrypted_key = pack("C*", @reencd_key);
															#create table enc_keys_mem
															#MEMORY tables can be expected to
															#disappear at will.
															my $prep_stmt2 = $con->prepare("CREATE TABLE IF NOT EXISTS enc_keys_mem (u_id integer unique, init_vec binary(16),aes_key binary(32)) ENGINE=MEMORY");	
															if ( $prep_stmt2 ) {
																my $rc = $prep_stmt2->execute();
																if ($rc) {
																	my $prep_stmt3 = $con->prepare("REPLACE INTO enc_keys_mem VALUES(?,?,?)");
																	if ($prep_stmt3) {
																		my $rc = $prep_stmt3->execute($u_id, $encrypted_iv, $encrypted_key);
																		if ( $rc ) {
																			use MIME::Base64 qw/encode_base64/;
																			my $encoded_sess_key = encode_base64($sess_key, "");
																			$session{"sess_key"} = $encoded_sess_key;
																			$success = 1;
																		}
																		else {
																			print STDERR "Could not execute INSERT INTO enc_keys_mem: ", $prep_stmt3->errstr, $/;  
																		}
																	}
																	else {
																		print STDERR "Could not prepare INSERT INTO enc_keys_mem: ", $prep_stmt3->errstr, $/;  
																	}
																}
																else {
																	print STDERR "Could not execute CREATE enc_keys_mem: ", $prep_stmt2->errstr, $/;  
																}
															}
															else {
																print STDERR "Could not prepare CREATE enc_keys_mem: ", $prep_stmt2->errstr, $/;  
															}
														}
													}
												}
											}
											else {
												print STDERR "Could not execute SELECT FROM users: ", $prep_stmt1->errstr, $/;
											}
										}
										else {
											print STDERR "Could not prepare SELECT FROM enc_keys: ", $prep_stmt1->errstr, $/;  
										}
									}
									if ($success) {
										$authd++;
										$session{"id"} = $valid[0];
										$session{"name"} = $valid[1];
										$session{"privileges"} = "all";
										$session{"token_expiry"} = 0;
										$uid = $valid[0];
										last;
									}
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM users: ", $prep_stmt->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM user: ", $prep_stmt->errstr, $/;  
					}
								
				}
				else {
					print STDERR $!;
				}
				$con->disconnect();	
			}
			else {
				$xss_attempt++;
			}
		}
	}
}

	print "Content-Type: text/html\r\n";
	my $res = "";
	#auth failed due to incorrect pass or incorrect auth token
	#or this was not an auth attempt--just a GET
	if (not $authd) {

		my $auth_token = gen_token();

		$session{"auth_token0"} = $auth_token;
		my @new_sess_array;
		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};	
		}
		my $new_sess = join ('&',@new_sess_array);
		print "X-Update-Session: $new_sess\r\n";
		
		$res .=
			'<!DOCTYPE html>
			<html lang="en">
			<head>';
			if ($login) {
				$res .=
					'<title>Spanj: Exam Management Information System - Login Failed</title>';
			}
			else {
				$res .=
				'<title>Spanj: Exam Management Information System - User Login</title>';
			}
		$res .=	
			'<title>Spanj: Exam Management Information System - Login Failed</title>
			<BASE target="_parent">
			<SCRIPT>
				function append_uname() {
					var u_name = strip_special_chars(document.getElementById("username").value);
					if (u_name !== "") {
						var url = document.getElementById("forgot_link").href + "&u_name=" + u_name;
						document.getElementById("forgot_link").href = url;
					}
				}
				function strip_special_chars(to_clean) {
					var cleaned = to_clean.replace(/[^A-Za-z0-9_\.\-]/, "");
					return cleaned;	
				}
			</SCRIPT>
			</head>
			<body>	
			<br/>
			<p><a href="/">Home</a> --&gt; <a href="/login.html">Login Options</a> --&gt; <a href="/cgi-bin/pwlogin.cgi?cont=' . 
			$cont . 
			'"> Login with Username/Password</a><p><h5>Spanj Exam Management Information System</h5>';
			if ($login) {
				
				if ($key_unlock) {
					$res .=	'<p><span style="color: red"><i>Could not unlock the security keys needed to manage the accounts MIS.</i> Perhaps the security keys were altered outside Spanj.</span><br>';
				}
				else {
					$res .=	'<p><span style="color: red"><i>Incorrect username or password</i></span><br>';
				}
			}
	
			if ($xss_attempt) {
				$res .= '<span style="color: red"><i>PS: Do not alter the login form</i></span></br>'; 
			}
		$res .=
			'<form autocomplete="off" method="POST" action="/cgi-bin/pwlogin.cgi?cont='.$cont.'">'.
			'<table>
			<tr>
			<td>
			<label for="username">Username</label>
			</td>
			<td>
			<input type="text" name="username" size="15" id="username"/>
			</td>
			</tr>

			<tr>
			<td>
			<label for="password">Password</label>
			</td>
			<td>
			<input type="password" name="password" size="15"/>';


		$res .=	"<input type=\"hidden\" name=\"auth_token0\" value=\"$auth_token\"/>";

		$res .=	'</td>
			</tr>

			<tr>
			<td>
			<input type="submit" name="submit" value="Login"/>
			</td>
			<td></td>
			</tr>

			</table>
			</form>
			<a href="/cgi-bin/forgotpassword.cgi?stage=1" id="forgot_link" onclick="append_uname()"><h5>Forgot Password?</h5></a>
			</body>

			</html>';
		my $content_len = length($res);
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
	}
	#auth successful
	elsif ($authd) {
		#correct pass/user-name provided
		if ($login) {
			$session{"auth_token0"} = "";
			my @new_sess_array;
			for my $sess_key (keys %session) {
				push @new_sess_array, $sess_key."=".$session{$sess_key};	
			}
			my $new_sess = join ('&',@new_sess_array);
			print "X-Update-Session: $new_sess\r\n";

			my @today = localtime; 
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
		        open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        		if ($log_f) {
                		@today = localtime;	
				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock($log_f, LOCK_EX) or print STDERR "Could not log logout due to flock error: $!$/";
                		print $log_f "$uid LOGIN $time\n";	
				flock($log_f, LOCK_UN);
                		close $log_f;
        		}
			else {
				print STDERR "Could not logout of $id: $!\n";
			}
		}
	
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: $cont\r\n";

		my $clean_url = htmlspecialchars($cont);	
        	my $res = 
                	"<html>
                	<head>
			<title>Spanj: Exam Management Information System - Redirect Failed</title>
			<base target=\"_parent\">
			</head>
               		<body>
                	You should have been redirected to <a href=\"$clean_url\">$clean_url</a>. If you were not, <a href=\"$clean_url\">Click Here</a> 
			</body>
                	</html>";
		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
	}


sub gen_token {
	my $len = 5 + int(rand 6);
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

